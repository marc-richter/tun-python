import os
import struct
import time
import numpy as np
import logging
from fcntl import ioctl
from scapy.layers.inet import IP, ICMP
from scapy.packet import Raw

# Configure logging
logging.basicConfig(level=logging.INFO, format=' %(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


def open_tun(device_name):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA

    flags = LINUX_IFF_TUN | LINUX_IFF_NO_PI
    ifs = struct.pack("16sH14s", device_name.encode(), flags, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    return tun


def bytes_to_bitarray(data):
    """Konvertiert Bytes zu einem Numpy-Bitarray"""
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def format_payload(payload):
    """Formatiert Nutzdaten in String und Hex"""
    try:
        text = payload.decode('utf-8', errors='replace')
    except UnicodeDecodeError:
        text = "[BINARY DATA]"

    hex_str = ' '.join(f"{b:02x}" for b in payload[:16])
    if len(payload) > 16:
        hex_str += " ..."

    return hex_str, text


if __name__ == "__main__":
    try:
        tun = open_tun("tun0")
        os.system("ip addr flush dev tun0 2>/dev/null")
        os.system("ip addr replace 192.0.2.2/24 dev tun0")
        os.system("ethtool -K tun0 tx off rx off 2>/dev/null")
        os.system("ip link set tun0 up mtu 1500 qlen 500")

        start_time = time.time()
        logging.info("Listening on tun0...")

        all_packets_bits = []

        while True:
            raw_packet = tun.read(1024)
            if raw_packet:
                hex_dump = raw_packet.hex()
                bit_array = bytes_to_bitarray(raw_packet)
                all_packets_bits.append(bit_array)

                try:
                    packet = IP(raw_packet)
                    logging.info(f"\n[SUCCESS] Packet ({time.time() - start_time:.2f}s)")
                    logging.info(f"Hex Dump: {hex_dump}")

                    if ICMP in packet:
                        icmp = packet[ICMP]
                        logging.info(f"ICMP Type: {icmp.type}, Code: {icmp.code}")

                        # Payload-Extraktion
                        if Raw in packet:
                            payload = packet[Raw].load
                            logging.info("Payload:")
                            if payload:
                                hex_str, text = format_payload(payload)
                                logging.info(f"   Text: {text}")
                                logging.info(f"   Hex : {hex_str}")
                                logging.info(f"   Bits: {bit_array[:20]}...")
                        else:
                            logging.info("Payload: [No payload detected]")

                except Exception as e:
                    logging.error("An error occurred while parsing the packet:")
                    logging.error(f"{hex_dump}")
                    logging.error(f"Bits: {bit_array[:20]}...")
                    logging.error(f"Error: {str(e)}")

            time.sleep(0.1)

    except KeyboardInterrupt:
        logging.error("Reader stopped")
        logging.error(f"Gespeicherte Pakete: {len(all_packets_bits)}")
    finally:
        tun.close()
