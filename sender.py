import logging
import socket
import time

from scapy.all import IP, ICMP, raw

logging.basicConfig(level=logging.INFO, format=' %(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')

def send_icmp():
    dst_ip = "192.0.2.1"  # Wichtig: Nicht die eigene Interface-IP!


    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

        for i in range(4):
            payload = f"FDIT_RADIOLAB_2025_Packet_{i+1}".encode()
            packet = IP(dst=dst_ip, ttl=64) / ICMP() / payload
            try:
                s.sendto(raw(packet), (dst_ip, 0))
                logging.info(f"Sent ICMP packet {i + 1}/4 to {dst_ip} (TTL: {packet.ttl})")
            except Exception as e:
                logging.error(f"Send error: {str(e)}")
            time.sleep(1.5)

if __name__ == "__main__":
    logging.info("Starting ICMP sender...")
    send_icmp()