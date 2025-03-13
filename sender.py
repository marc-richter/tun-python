import logging
import socket
import time
import os
import argparse
from scapy.all import IP, ICMP, raw

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


def send_data(dst_ip, image_path=None, protocol=0xFD):
    """
    Sendet ICMP-Pakete und/oder Bilddaten in IP-Paketen
    :param dst_ip: Ziel-IP-Adresse
    :param image_path: Pfad zum Bild
    :param protocol: IP-Protokollnummer (0xFD=253 für benutzerdefinierte Daten)
    """
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

        # ICMP-Pakete senden
        for i in range(4):
            payload = f"FDIT_RADIOLAB_2025_Packet_{i + 1}".encode()
            icmp_packet = IP(dst=dst_ip, ttl=64) / ICMP() / payload
            try:
                s.sendto(raw(icmp_packet), (dst_ip, 0))
                logging.info(f"Sent ICMP packet {i + 1}/4 to {dst_ip}")
            except Exception as e:
                logging.error(f"ICMP Send error: {str(e)}")
            time.sleep(0.5)

        # Bild senden wenn angegeben
        if image_path:
            if not os.path.exists(image_path):
                logging.error(f"Bild nicht gefunden: {image_path}")
                return

            try:
                with open(image_path, "rb") as f:
                    image_data = f.read()
                    chunk_size = 1400

                    for idx, i in enumerate(range(0, len(image_data), chunk_size)):
                        chunk = image_data[i:i + chunk_size]
                        ip_packet = IP(
                            dst=dst_ip,
                            ttl=64,
                            proto=protocol
                        ) / chunk

                        s.sendto(raw(ip_packet), (dst_ip, 0))
                        logging.info(f"Sent image chunk {idx + 1} ({len(chunk)} bytes)")
                        time.sleep(0.01)

                    # Endsignal senden
                    end_signal = b"END_OF_IMAGE"
                    end_packet = IP(dst=dst_ip, ttl=64, proto=protocol) / end_signal
                    s.sendto(raw(end_packet), (dst_ip, 0))
                    logging.info(f"Sent end signal for image: {len(image_data)} bytes total")

            except Exception as e:
                logging.error(f"Bildsendefehler: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daten-Sender")
    parser.add_argument("dst_ip", help="Ziel-IP-Adresse")
    parser.add_argument("-i", "--image", help="Pfad zum zu sendenden Bild")
    parser.add_argument("-p", "--protocol", type=int, default=253,
                        help="IP-Protokollnummer für Bilddaten (default: 253)")

    args = parser.parse_args()

    logging.info("Starting sender...")
    send_data(args.dst_ip, args.image, args.protocol)
