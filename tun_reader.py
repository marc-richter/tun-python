import argparse
import logging
import struct
import time
from fcntl import ioctl

import numpy as np
from PIL import Image
from scapy.layers.inet import IP, ICMP
from scapy.packet import Raw

from ImageReassembler import ImageReassembler

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')

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


def bytes_to_bitarray(data, max_bits=128):
    """Konvertiert Bytes in eine Binärdarstellung"""
    try:
        # Versuche mit numpy für optimierte Performance
        arr = np.frombuffer(data[:max_bits // 8], dtype=np.uint8)
        bits = np.unpackbits(arr)
        bit_str = ''.join(str(b) for b in bits)
    except Exception:
        # Fallback ohne numpy
        bit_str = ''.join(format(byte, '08b') for byte in data[:max_bits // 8])

    if len(data) * 8 > max_bits:
        bit_str += f"... ({len(data) * 8} bits)"
    return bit_str


def format_icmp_payload(payload):
    """Formatiert ICMP-Payload für detailliertes Logging"""
    try:
        # Hex-Darstellung der ersten 32 Bytes
        hex_str = ' '.join(f"{b:02x}" for b in payload[:32])
        if len(payload) > 32:
            hex_str += f" ... (+{len(payload) - 32} bytes)"

        # Textdarstellung mit Ersetzung nicht-druckbarer Zeichen
        text = ''.join(
            c if 32 <= ord(c) < 127 else f'\\x{ord(c):02x}'
            for c in payload[:64].decode('utf-8', errors='replace')
        )

        # Bitdarstellung der ersten 128 bits (16 Bytes)
        bit_str = bytes_to_bitarray(payload)

        return (
            f"Hex: {hex_str}\n"
            f"Text: {text}\n"
            f"Bits: {bit_str}"
        )
    except Exception as e:
        return f"Payload Format Error: {str(e)}"


def process_packet(packet, reassembler, protocol):
    """Verarbeitet Netzwerkpakete und gibt Verarbeitungsstatus zurück"""
    try:
        if packet.proto == protocol:
            return handle_custom_protocol(packet, reassembler)

        if ICMP in packet:
            handle_icmp(packet)

    except Exception as e:
        logging.error(f"Paketverarbeitungsfehler: {str(e)}")
        return False
    return True


def handle_custom_protocol(packet, reassembler):
    """Verarbeitet benutzerdefinierte Protokollpakete"""
    src_ip = packet.src
    payload = bytes(packet.payload)

    # Endsignal-Erkennung
    if payload == b"END_OF_IMAGE":
        logging.info(f"🔚 Endsignal von {src_ip} erhalten")
        reassembler.save_image(src_ip)
        return True

    # Datenpaket verarbeiten
    is_end = reassembler.add_packet(src_ip, payload)
    logging.info(f"📦 Segment von {src_ip}: {len(payload)} Bytes")
    return is_end


def handle_icmp(packet):
    """Verarbeitet ICMP-Pakete mit detailliertem Payload-Logging"""
    icmp = packet[ICMP]
    logging.info("\n" + "=" * 40)
    logging.info(f"🛰 ICMP Paket von {packet.src}")
    logging.info(f"Type: {icmp.type}, Code: {icmp.code}")

    if Raw in packet:
        payload = packet[Raw].load
        if payload:
            formatted = format_icmp_payload(payload)
            logging.info(f"Payload Details:\n{formatted}")

    logging.info("=" * 40 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--protocol", type=int, default=253,
                        help="IP-Protokollnummer (default: 253)")
    args = parser.parse_args()

    reassembler = ImageReassembler()
    tun = None

    try:
        tun = open_tun("tun0")
        logging.info("🎧 Empfangsbereit auf tun0...")

        while True:
            try:
                raw_packet = tun.read(65535)
                # TODO: tun.write() schreiben damit die Daten in den TUN-Adapter geschrieben werden als Empfänger
                if raw_packet:
                    packet = IP(raw_packet)
                    process_packet(packet, reassembler, args.protocol)

                # Timeout-Check alle 30 Sekunden
                if time.time() % 30 < 0.01:
                    reassembler.check_timeouts()

                time.sleep(0.001)

            except KeyboardInterrupt:
                logging.info("⏹ Abbruch durch Benutzer...")
                break
            except Exception as e:
                logging.error(f"💥 Kritischer Fehler: {str(e)}")
                break

    finally:
        if tun:
            tun.close()
        logging.info("💾 Speichere verbleibende Daten...")
        reassembler.save_all()
        logging.info("🧹 Bereinigung abgeschlossen.")


if __name__ == "__main__":
    main()