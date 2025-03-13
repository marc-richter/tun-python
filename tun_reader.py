import os
import struct
import time
import numpy as np
import logging
import argparse
from collections import defaultdict
from fcntl import ioctl
from scapy.layers.inet import IP, ICMP
from scapy.packet import Raw
from PIL import Image
import io


# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


class ImageReassembler:
    def __init__(self):
        self.image_buffers = defaultdict(bytes)
        self.last_received = defaultdict(float)
        self.timeout = 5

    def add_packet(self, src_ip, data):
        if data == b"END_OF_IMAGE":
            self.save_image(src_ip)
            return True
        self.image_buffers[src_ip] += data
        self.last_received[src_ip] = time.time()
        return False

    def save_image(self, src_ip):
        data = self.image_buffers.get(src_ip)
        if not data:
            logging.error(f"Keine Daten zum Speichern von {src_ip}")
            return

        directory = "/app/data/received"
        os.makedirs(directory, exist_ok=True)
        filename = os.path.join(directory, f"received_{src_ip}_{int(time.time())}.png")
        try:
            # Konvertiere die Rohdaten in ein Pillow Image-Objekt
            image = Image.open(io.BytesIO(data))
            # Speichere das Bild im PNG-Format
            image.save(filename, format="PNG")
            logging.info(f"Bild gespeichert: {filename} ({len(data)} bytes)")
            del self.image_buffers[src_ip]
            del self.last_received[src_ip]
        except Exception as e:
            logging.error(f"Speicherfehler {filename}: {str(e)}")


def open_tun(device_name):
    """
    Opens a TUN (network tunnel) device.

    This function configures and opens a TUN device, which is a virtual network interface used for tunneling IP packets.

    Parameters:
    device_name (str): The name of the TUN device to be created (e.g., 'tun0').

    Constants:
    LINUX_IFF_TUN (int): Flag to specify the creation of a TUN device (0x0001).
                         TUN devices operate at the network layer (Layer 3) and handle IP packets.
    LINUX_IFF_NO_PI (int): Flag to disable the inclusion of packet information (PI) in the data stream (0x1000).
                           This means that the TUN device will not prepend a header with protocol information to the packets.
    LINUX_TUNSETIFF (int): IOCTL request code to configure the TUN device (0x400454CA).
                           This code is used to set the interface flags and name for the TUN device.

    Returns:
    file object: A file object representing the opened TUN device, which can be used for reading and writing IP packets.
    """
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA

    flags = LINUX_IFF_TUN | LINUX_IFF_NO_PI
    # 16s (string): Interface name, H (unsigned short): Flags, 14s: Padding
    struct_pack_format = "16sH14s"
    ifs = struct.pack(struct_pack_format, device_name.encode(), flags, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    return tun


def bytes_to_bitarray(data):
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def format_payload(payload):
    try:
        text = payload.decode('utf-8', errors='replace')
    except UnicodeDecodeError:
        text = "[BINARY DATA]"

    hex_str = ' '.join(f"{b:02x}" for b in payload[:16])
    if len(payload) > 16:
        hex_str += " ..."
    return hex_str, text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--protocol", type=int, default=253,
                        help="IP Protokollnummer für Bilddaten")
    args = parser.parse_args()

    reassembler = ImageReassembler()

    try:
        tun = open_tun("tun0")

        logging.info("Listening on tun0...")

        while True:
            raw_packet = tun.read(65535)
            if raw_packet:
                try:
                    packet = IP(raw_packet)

                    # Bilddaten verarbeiten
                    if packet.proto == args.protocol:
                        src_ip = packet.src
                        payload = bytes(packet.payload)
                        is_end = reassembler.add_packet(src_ip, payload)
                        if is_end:
                            logging.info(f"Endsignal empfangen von {src_ip}")
                        else:
                            logging.info(f"Bildsegment von {src_ip} empfangen ({len(payload)} bytes)")
                        continue

                    # ICMP verarbeiten
                    if ICMP in packet:
                        icmp = packet[ICMP]
                        logging.info(f"\nICMP Paket von {packet.src}")
                        logging.info(f"Type: {icmp.type}, Code: {icmp.code}")

                        if Raw in packet:
                            payload = packet[Raw].load
                            if payload:
                                hex_str, text = format_payload(payload)
                                logging.info(f"Text: {text}")
                                logging.info(f"Hex: {hex_str}")

                except Exception as e:
                    logging.error(f"Verarbeitungsfehler: {str(e)}")

            # Timeout prüfen alle 2 Sekunden
            if time.time() % 2 < 0.1:
                reassembler.check_timeouts()

            time.sleep(0.01)

    except KeyboardInterrupt:
        logging.info("Speichere verbleibende Bilder...")
        for ip in list(reassembler.image_buffers.keys()):
            reassembler.save_image(ip)
    finally:
        tun.close()

