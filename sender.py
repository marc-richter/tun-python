import socket
import time
from scapy.all import IP, ICMP, raw


def send_icmp():
    dst_ip = "192.0.2.1"  # Wichtig: Nicht die eigene Interface-IP!
    packet = IP(dst=dst_ip, ttl=64) / ICMP() / b"TESTPAYLOAD_TUN_123"

    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

        for i in range(4):
            try:
                s.sendto(raw(packet), (dst_ip, 0))
                print(f"Sent ICMP packet {i + 1}/4 to {dst_ip} (TTL: {packet.ttl})")
            except Exception as e:
                print(f"Send error: {str(e)}")
            time.sleep(1.5)


if __name__ == "__main__":
    print("\nStarting ICMP sender...")
    send_icmp()
