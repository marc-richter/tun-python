import argparse
import logging
import struct
from datetime import datetime

import pika
from scapy.layers.inet import IP, TCP, ICMP

from common import open_tun

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')

# RabbitMQ Konfiguration
RABBITMQ_HOST = 'rabbitmq'
REQUEST_QUEUE = 'network_request'
REPLY_QUEUE = 'network_reply'


class RabbitMQClient:
    def __init__(self, tun=None):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(REQUEST_QUEUE)
        self.channel.queue_declare(REPLY_QUEUE)
        self.tun = tun
        self.channel.basic_consume(
            queue=REPLY_QUEUE,
            on_message_callback=self.handle_reply,
            auto_ack=True
        )

    def publish_request(self, packet):
        self.channel.basic_publish(
            exchange='',
            routing_key=REQUEST_QUEUE,
            body=packet
        )
        logging.info(f"Paket an RabbitMQ gesendet: {len(packet)} bytes")

    def handle_reply(self, ch, method, properties, body, tun):
        if tun:
            tun.write(body)
            logging.info(f"Antwortpaket empfangen: {len(body)} bytes")


class TrafficLogger:
    def __init__(self):
        self.log_file = open("/var/log/tun_traffic.bin", "ab")

    def log_packet(self, packet):
        ts = datetime.now().timestamp()
        header = struct.pack("!dI", ts, len(packet))
        self.log_file.write(header + packet)
        self.log_file.flush()





def process_packet(raw_packet, tun, logger, rabbit):
    try:
        logger.log_packet(raw_packet)
        packet = IP(raw_packet)

        if packet.haslayer(ICMP) and packet[ICMP].type == 8:
            logging.info(f"ICMP-Anfrage von {packet[IP].src} weitergeleitet")
            rabbit.publish_request(raw_packet)

        elif packet.haslayer(TCP) and packet[TCP].dport == 8080:
            ip = packet[IP]
            tcp = packet[TCP]
            logging.info(f"TCP-Anfrage an Port 8080: {ip.src}:{tcp.sport}")

    except Exception as e:
        logging.error(f"Paketverarbeitungsfehler: {str(e)}")


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    logger = TrafficLogger()

    tun = open_tun()
    rabbit = RabbitMQClient(tun)

    try:
        logging.info("TUN-Listener gestartet (RabbitMQ-Modus)")
        while True:
            raw_packet = tun.read(65535)
            if raw_packet:
                process_packet(raw_packet, tun, logger, rabbit)
            rabbit.connection.process_data_events()
    finally:
        tun.close()
        logger.log_file.close()
        rabbit.connection.close()


if __name__ == "__main__":
    main()
