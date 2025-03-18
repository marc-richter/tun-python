import logging
import time
import signal
import select
import os

import pika
from scapy.layers.inet import IP, ICMP
from scapy.error import Scapy_Exception

from common import open_tun, REQUEST_QUEUE, REPLY_QUEUE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class TunnelManager:
    def __init__(self):
        self.shutdown = False
        self.tun = None
        self.connection = None
        self.channel = None
        self.reconnect_delay = 5

        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, signum, frame):
        logging.info(f"Signal {signum} empfangen, initiiere Shutdown...")
        self.shutdown = True

    def init_tun(self):
        """Öffnet das TUN-Device ohne Konfiguration"""
        try:
            self.tun = open_tun()
            logging.info(f"TUN-Device geöffnet (fd={self.tun.fileno()})")
            return True
        except Exception as e:
            logging.error(f"TUN-Fehler: {str(e)}")
            return False

    def init_rabbitmq(self):
        """Stellt die RabbitMQ-Verbindung her"""
        try:
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host='rabbitmq',
                    credentials=pika.PlainCredentials('user', 'pass'),
                    heartbeat=25,
                    blocked_connection_timeout=30,
                    connection_attempts=3,
                    retry_delay=5
                )
            )
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

            logging.info("RabbitMQ-Verbindung erfolgreich")
            return True
        except Exception as e:
            logging.error(f"RabbitMQ-Fehler: {str(e)}")
            return False

    def process_message(self):
        """Verarbeitet eine einzelne Nachricht"""
        method, _, body = self.channel.basic_get(
            queue=REQUEST_QUEUE,
            auto_ack=False
        )

        if not method:
            return False

        try:
            packet = IP(body)
            logging.info(f"Anfrage von container_a aus Queue erhalten, von {packet[IP].src} nach {packet[IP].dst}")
            if not packet.haslayer(ICMP) or packet[ICMP].type != 8:
                raise ValueError("Ungültiger ICMP-Request")

            # Schreibe ins TUN
            self.tun.write(bytes(packet))
            self.channel.basic_ack(method.delivery_tag)
            logging.info(f"Ping Anfrage an TUN gesendet")

            # Warte auf Antwort von OS
            start_time = time.time()
            while time.time() - start_time < 2:
                ready, _, _ = select.select([self.tun], [], [], 0.5)
                if ready:
                    # Lese Antwort aus TUN von OS
                    response = self.tun.read(65535)
                    response_packet = IP(response)

                    if response_packet.haslayer(ICMP) and response_packet[ICMP].type == 0:
                        logging.info(f"Antwort von TUN (OS) erhalten, von {response_packet[IP].src} nach {response_packet[IP].dst}, byte string {response}")
                        self.channel.basic_publish(
                            exchange='',
                            routing_key=REPLY_QUEUE,
                            body=bytes(response_packet),
                            properties=pika.BasicProperties(
                                delivery_mode=2,
                                timestamp=int(time.time())
                            )
                        )
                        logging.info(f"Antwort queue {REPLY_QUEUE} fuer container_a gesendet")
                        return True

            logging.warning("Timeout bei Antwort")
            return True

        except (Scapy_Exception, ValueError) as e:
            logging.warning(f"Ungültiges Paket: {str(e)}")
            self.channel.basic_nack(method.delivery_tag, requeue=False)
        except Exception as e:
            logging.error(f"Verarbeitungsfehler: {str(e)}")
            self.channel.basic_nack(method.delivery_tag, requeue=True)
            raise

    def run_loop(self):
        """Hauptprozess"""
        while not self.shutdown:
            try:
                if not self.init_tun() or not self.init_rabbitmq():
                    time.sleep(self.reconnect_delay)
                    continue

                logging.info("Bereit für Nachrichten")
                while not self.shutdown:
                    if self.process_message():
                        continue
                    time.sleep(0.1)

            except pika.exceptions.ConnectionClosed:
                logging.warning("RabbitMQ-Verbindung unterbrochen")
                self.cleanup()
                time.sleep(5)
            except Exception as e:
                logging.error(f"Kritischer Fehler: {str(e)}")
                self.cleanup()
                time.sleep(5)

    def cleanup(self):
        """Ressourcen freigeben"""
        try:
            if self.connection and self.connection.is_open:
                self.connection.close()
            if self.tun and not self.tun.closed:
                self.tun.close()
        except Exception:
            pass

        logging.info("Cleanup durchgeführt")


if __name__ == "__main__":
    logging.info("Container B Start")
    manager = TunnelManager()
    try:
        manager.run_loop()
    except KeyboardInterrupt:
        pass
    finally:
        manager.cleanup()
        logging.info("Container B Ende")
        os._exit(0)
