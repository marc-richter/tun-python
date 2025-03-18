import argparse
import fcntl
import logging
import struct
import socket
from datetime import datetime
from time import sleep

import pika
from pika.exceptions import AMQPConnectionError
from scapy.compat import raw
from scapy.layers.inet import IP, TCP, ICMP

from common import REQUEST_QUEUE, REPLY_QUEUE

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


class RabbitMQClient:
    def __init__(self, tun=None):
        self.tun = tun
        self.max_retries = 5
        self.connection = self.create_connection()
        self.init_channel()

    def create_connection(self):
        for attempt in range(self.max_retries):
            try:
                return pika.BlockingConnection(
                    pika.ConnectionParameters(
                        host='172.18.0.2',
                        port=5672,
                        credentials=pika.PlainCredentials('user', 'pass'),
                        heartbeat=30,
                        blocked_connection_timeout=60,
                        retry_delay=5,
                        connection_attempts=3
                    )
                )
            except Exception as e:
                logging.warning(f"Verbindungsversuch {attempt + 1}/{self.max_retries} fehlgeschlagen: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise AMQPConnectionError(f"Verbindung nach {self.max_retries} Versuchen fehlgeschlagen")
                sleep(5)

    def init_channel(self):
        self.channel = self.connection.channel()
        self.channel.queue_declare(
            queue=REQUEST_QUEUE,
            durable=True,
            arguments={'x-queue-type': 'quorum'}
        )
        self.channel.queue_declare(
            queue=REPLY_QUEUE,
            durable=True,
            arguments={'x-queue-type': 'quorum'}
        )
        logging.info(f"Start listening on {REPLY_QUEUE}")
        self.channel.basic_consume(
            queue=REPLY_QUEUE,
            on_message_callback=self.handle_reply,
            auto_ack=False
        )

    def publish_request(self, packet):
        try:
            self.channel.basic_publish(
                exchange='',
                routing_key=REQUEST_QUEUE,
                body=packet,
                properties=pika.BasicProperties(delivery_mode=2)
            )
            logging.info(f"Paket ({len(packet)} Bytes) an RabbitMQ gesendet")
        except Exception as e:
            logging.error(f"Fehler beim Senden: {str(e)}")
            self.reconnect()

    def handle_reply(self, ch, method, properties, body):
        try:
            response = IP(body)
            logging.info(f"Antwort von container_b aus Queue erhalten: {response[IP].src} nach {response[IP].dst} erhalten")
            if response.haslayer(ICMP) and response[ICMP].type == 0:
                # Erzwinge Neuberechnung der Checksumme
                del response[ICMP].chksum
                response = IP(raw(response))
                self.tun.write(raw(response))
                logging.info(f"Antwort an TUN geschrieben")
                ch.basic_ack(method.delivery_tag)
        except Exception as e:
            logging.error(f"Antwortverarbeitung fehlgeschlagen: {str(e)}")
            ch.basic_nack(method.delivery_tag)

    def reconnect(self):
        logging.info("Versuche Reconnect...")
        self.connection = self.create_connection()
        self.init_channel()

class TrafficLogger:
    def __init__(self):
        self.log_file = open("/var/log/tun_traffic.bin", "ab")

    def log_packet(self, packet):
        ts = datetime.now().timestamp()
        header = struct.pack("!dI", ts, len(packet))
        self.log_file.write(header + packet)
        self.log_file.flush()

def open_tun(device="tun0"):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    ifr = struct.pack("16sH22s", device.encode(), 0x0001 | 0x1000, b"")  # Korrektur des struct
    fcntl.ioctl(tun, 0x400454CA, ifr)
    return tun

def process_packet(raw_packet, tun, logger, rabbit):
    try:
        logger.log_packet(raw_packet)
        packet = IP(raw_packet)

        if packet.haslayer(ICMP) and packet[ICMP].type == 8:
            logging.info(f"ICMP Request von {packet[IP].src} nach {packet[IP].dst}, hex: {packet[ICMP].load.hex()}")
            rabbit.publish_request(raw_packet)

        elif packet.haslayer(TCP) and packet[TCP].dport == 8080:
            logging.info(f"TCP Request auf Port 8080: {packet[IP].src}:{packet[TCP].sport}")

    except Exception as e:
        logging.error(f"Verarbeitungsfehler: {str(e)}")

def main():
    logger = TrafficLogger()
    tun = open_tun()

    try:
        rabbit = RabbitMQClient(tun)
        logging.info("TUN-Listener aktiv (RabbitMQ-Modus)")

        while True:
            raw_packet = tun.read(65535)
            if raw_packet:
                process_packet(raw_packet, tun, logger, rabbit)
            rabbit.connection.process_data_events(time_limit=1)

    except KeyboardInterrupt:
        pass
    finally:
        tun.close()
        logger.log_file.close()
        if 'rabbit' in locals():
            rabbit.connection.close()

if __name__ == "__main__":
    main()
