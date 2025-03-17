import argparse
import logging
import os
import struct
import random
from datetime import datetime
from fcntl import ioctl
from scapy.layers.inet import IP, TCP, ICMP
from scapy.packet import Raw
from collections import defaultdict

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


class TrafficLogger:
    def __init__(self):
        self.log_file = open("/var/log/tun_traffic.bin", "ab")

    def log_packet(self, packet):
        ts = datetime.now().timestamp()
        header = struct.pack("!dI", ts, len(packet))
        self.log_file.write(header + packet)
        self.log_file.flush()
        logging.info(f"Logged packet: {len(packet)} bytes")


class ConnectionTracker:
    def __init__(self):
        self.connections = defaultdict(dict)
        self.base_seq = random.getrandbits(32)
        self.seq_increment = 64000 + (os.getpid() % 1000)  # Zufälliges Inkrement

    def get_next_seq(self):
        self.base_seq = (self.base_seq + self.seq_increment) % 0xFFFFFFFF
        return self.base_seq

    def create_connection(self, key, client_seq):
        server_seq = self.get_next_seq()
        self.connections[key] = {
            'server_seq': (server_seq + 1) % 0xFFFFFFFF,
            'client_seq': (client_seq + 1) % 0xFFFFFFFF,
            'status': 'SYN_RECEIVED'
        }
        return server_seq


def open_tun(device_name="tun0"):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    ifr = struct.pack("16sH", device_name.encode(), 0x0001 | 0x1000)
    ioctl(tun, 0x400454CA, ifr)
    logging.info(f"TUN-Interface {device_name} geöffnet")
    return tun


def handle_http_request(packet, tun, conn_tracker):
    ip = packet[IP]
    tcp = packet[TCP]
    key = (ip.src, ip.dst, tcp.sport, tcp.dport)

    if tcp.payload and key in conn_tracker.connections:
        payload = bytes(tcp.payload).decode('utf-8', 'ignore')
        logging.info(f"HTTP-Anfrage erhalten: {payload.splitlines()[0] if payload else ''}")

        if 'GET /hello-world' in payload:
            response_body = "Hello World"
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n"
                f"Content-Length: {len(response_body)}\r\n\r\n"
                f"{response_body}"
            ).encode()

            response_pkt = IP(
                src=ip.dst,
                dst=ip.src
            ) / TCP(
                sport=tcp.dport,
                dport=tcp.sport,
                seq=conn_tracker.connections[key]['server_seq'],
                ack=(tcp.seq + len(tcp.payload)) % 0xFFFFFFFF,
                flags='PA'
            ) / response

            logging.info(f"Response Payload String: {response.decode('utf-8', 'ignore')}")
            logging.info(f"Response in Bytes: {bytes(response_pkt)}")
            logging.info(f"HTTP-Response von {ip.dst} -> {ip.src} gesendet")

            tun.write(bytes(response_pkt))


            # Update sequence number with overflow protection
            new_seq = (conn_tracker.connections[key]['server_seq'] + len(response)) % 0xFFFFFFFF
            conn_tracker.connections[key]['server_seq'] = new_seq

            # FIN senden
            fin_pkt = IP(src=ip.dst, dst=ip.src) / TCP(
                sport=tcp.dport,
                dport=tcp.sport,
                seq=new_seq,
                ack=(tcp.seq + len(tcp.payload)) % 0xFFFFFFFF,
                flags='FA'
            )
            tun.write(bytes(fin_pkt))
            logging.info("FIN gesendet")

            del conn_tracker.connections[key]


def process_packet(raw_packet, tun, logger, conn_tracker):
    try:
        logger.log_packet(raw_packet)
        packet = IP(raw_packet)

        if packet.haslayer(ICMP) and packet[ICMP].type == 8:
            logging.info(f"Ping-Anfrage von {packet[IP].src} empfangen")
            logging.info(f"Ping-Anfrage in Bytes: {bytes(packet)}")
            response = IP(
                src=packet[IP].dst,
                dst=packet[IP].src,
                ttl=64
            ) / ICMP(
                type=0,
                id=packet[ICMP].id,
                seq=packet[ICMP].seq
            ) / packet[Raw].load

            tun.write(bytes(response))
            logging.info(f"Ping response in bytes: {bytes(response)}")
            logging.info(f"Ping-Response an {packet[IP].src} gesendet")

        elif packet.haslayer(TCP) and packet[TCP].dport == 8080:
            ip = packet[IP]
            tcp = packet[TCP]
            key = (ip.src, ip.dst, tcp.sport, tcp.dport)

            logging.info(f"TCP-Paket empfangen: {ip.src}:{tcp.sport} -> {ip.dst}:{tcp.dport}")
            # log http payload as utf8 string
            if tcp.payload:
                logging.info(f"HTTP-Payload: {bytes(tcp.payload).decode('utf-8', 'ignore')}")

            if tcp.flags & 0x02:  # SYN
                logging.info(f"TCP SYN von {ip.src} empfangen (Client SEQ: {tcp.seq})")
                server_seq = conn_tracker.create_connection(key, tcp.seq)

                syn_ack = IP(src=ip.dst, dst=ip.src) / TCP(
                    sport=tcp.dport,
                    dport=tcp.sport,
                    seq=server_seq,
                    ack=(tcp.seq + 1) % 0xFFFFFFFF,
                    flags='SA'
                )
                tun.write(bytes(syn_ack))
                logging.info(f"SYN-ACK gesendet (SEQ: {server_seq}, ACK: {(tcp.seq + 1) % 0xFFFFFFFF})")

            elif tcp.flags & 0x10:  # ACK
                logging.info(f"TCP ACK von {ip.src} empfangen (Client SEQ: {tcp.seq}, ACK: {tcp.ack})")
                if key in conn_tracker.connections:
                    expected_ack = (conn_tracker.connections[key]['server_seq']) % 0xFFFFFFFF  # SEQ+1 des SYN-ACKs
                    if tcp.ack == expected_ack:
                        conn_tracker.connections[key]['status'] = 'ESTABLISHED'
                        logging.info("TCP-Verbindung etabliert")
                        handle_http_request(packet, tun, conn_tracker)  # HIER ANPASSEN

            elif tcp.flags & 0x01:  # FIN
                    if key in conn_tracker.connections:
                        logging.info("TCP FIN empfangen")
                        del conn_tracker.connections[key]

    except Exception as e:
        logging.error(f"Verarbeitungsfehler: {str(e)}")


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    logger = TrafficLogger()
    conn_tracker = ConnectionTracker()
    tun = open_tun()

    try:
        logging.info("TUN-Listener gestartet (GLOBAL MODE)")
        while True:
            raw_packet = tun.read(65535)
            if raw_packet:
                process_packet(raw_packet, tun, logger, conn_tracker)
    finally:
        tun.close()
        logger.log_file.close()


if __name__ == "__main__":
    main()
