import argparse
import logging
import struct
from datetime import datetime
from time import sleep

import pika
from pika.exceptions import AMQPConnectionError
from scapy.layers.inet import IP, TCP, ICMP

from common import open_tun, REPLY_QUEUE, REQUEST_QUEUE

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')

# Vorher
RABBITMQ_HOST = 'rabbitmq'

# Nachher (mit Authentifizierung und Port)
RABBITMQ_CREDENTIALS = pika.PlainCredentials('user', 'pass')
RABBITMQ_PARAMS = pika.ConnectionParameters(
    host='rabbitmq',
    port=5672,
    virtual_host='/',
    credentials=RABBITMQ_CREDENTIALS,
    heartbeat=600,
    blocked_connection_timeout=300
)

class RabbitMQClient:
    def __init__(self, tun=None):
        self.tun = tun
        self.reconnect_delay = 5
        self.max_retries = 5
        self.connection = self.create_connection()
        self.init_channel()

    def create_connection(self):
        for i in range(self.max_retries):
            try:
                return pika.BlockingConnection(RABBITMQ_PARAMS)
            except Exception as e:
                if i == self.max_retries -1:
                    raise
                logging.warning(f"Verbindungsfehler (Versuch {i+1}/{self.max_retries}): {str(e)}")
                sleep(self.reconnect_delay)
        raise AMQPConnectionError("Maximale Verbindungsversuche erreicht")

    def init_channel(self):
        self.channel = self.connection.channel()
        self.channel.queue_declare(
            queue=REQUEST_QUEUE,
            durable=True,
            arguments={
                'x-queue-type': 'quorum',
                'x-dead-letter-exchange': 'dead_letters'
            }
        )

        self.channel.queue_declare(
            queue=REPLY_QUEUE,
            durable=True,
            arguments={
                'x-queue-type': 'quorum',
                'x-dead-letter-exchange': 'dead_letters'
            }
        )

    def publish_request(self, packet):
        self.channel.basic_publish(
            exchange='',
            routing_key=REQUEST_QUEUE,
            body=packet
        )
        logging.info(f"Paket an RabbitMQ gesendet: {len(packet)} bytes")

    def handle_reply(self, ch, method, properties, body):
        try:
            if self.tun and body:
                self.tun.write(body)
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logging.info(f"Antwort verarbeitet: {len(body)} Bytes")
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception as e:
            logging.error(f"Fehler bei Antwortverarbeitung: {str(e)}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


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
