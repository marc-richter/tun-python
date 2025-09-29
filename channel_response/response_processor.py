# response_processor.py
import logging
import pika
import threading
import random
import numpy as np
import queue
import time
import yaml
from common import REPLY_QUEUE, REPLY_QUEUE_AFTER_CHANNEL

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ResponseProcessor:
    def __init__(self, config):
        self.config = config['reply_channel']
        self.retry_config = config.get('retry', {
            'max_retries': 5,
            'base_delay': 1000,
            'jitter': 500
        })
        self.ack_queue = queue.Queue()  # Thread-sichere Ack-Queue
        self._init_connection()

    def _init_connection(self):
        """Initialisiert eine neue RabbitMQ-Verbindung"""
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host='rabbitmq',
                credentials=pika.PlainCredentials('admin', 'admin'),
                heartbeat=300,
                blocked_connection_timeout=300,
                connection_attempts=10,
                retry_delay=5,
                socket_timeout=120
            )
        )
        self.channel = self.connection.channel()
        self._declare_queues()

    def _declare_queues(self):
        """Deklariert alle benötigten Queues"""
        quorum_args = {'x-queue-type': 'quorum'}

        self.channel.queue_declare(
            queue=REPLY_QUEUE,
            durable=True,
            arguments=quorum_args
        )
        self.channel.queue_declare(
            queue=REPLY_QUEUE_AFTER_CHANNEL,
            durable=True,
            arguments=quorum_args
        )

    def _reconnect(self):
        """Stellt die Verbindung neu her"""
        logger.warning("Versuche Reconnect...")
        try:
            if self.connection.is_open:
                self.connection.close()
        except Exception:
            pass
        self._init_connection()

    def _calculate_delay(self):
        """Berechnet die Verzögerung mit Jitter"""
        dist_type = self.config['distribution']['type']
        dist_params = self.config['distribution']['parameters']

        if dist_type == 'exponential':
            delay = np.random.exponential(dist_params['lambda'])
        elif dist_type == 'normal':
            delay = np.random.normal(dist_params['mu'], dist_params['sigma'])
        elif dist_type == 'uniform':
            # Korrektur für Uniform-Verteilung
            delay = random.uniform(
                dist_params['min_delay'],
                dist_params['max_delay']
            )
        else:
            delay = random.uniform(0, self.config['max_delay'])

        delay += random.uniform(-self.config['jitter'], self.config['jitter'])
        return max(
            self.config['min_delay'],
            min(delay, self.config['max_delay'])
        )

    def _process_message(self, ch, method, properties, body):
        """Verarbeitet eine eingehende Nachricht"""

        # hier die channel.yml neu einlesen
        #with open('channel.yml') as f:
        #   confige = yaml.safe_load(f)
        #self.config = confige['reply_channel']  # sicherstellen, dass die neuen channel Parameter auch immer überall bereitgestellt werden
        with open('channel.yml') as f:
            confige = yaml.safe_load(f)
        self.config = confige['reply_channel']


        logger.info(f"Verarbeite Nachricht aus {REPLY_QUEUE}: {body[:20]}...")

        if random.random() < self.config['drop_probability']:
            logger.warning(f"Response verworfen: {body[:20]}...")
            # Kein ACK - Nachricht wird neu zugestellt
            return

        delay = self._calculate_delay()
        logger.info(f"Verzögere Response um {delay:.2f}ms: {body[:20]}...")

        def forward_message():
            try:
                # Neue Verbindung für Weiterleitung
                with pika.BlockingConnection(
                        pika.ConnectionParameters(
                            host='rabbitmq',
                            credentials=pika.PlainCredentials('admin', 'admin')
                        )
                ) as conn:
                    channel = conn.channel()
                    channel.basic_publish(
                        exchange='',
                        routing_key=REPLY_QUEUE_AFTER_CHANNEL,
                        body=body,
                        properties=pika.BasicProperties(
                            headers=properties.headers,
                            delivery_mode=2
                        )
                    )
                    logger.info(f"Response an {REPLY_QUEUE_AFTER_CHANNEL} gesendet")
                    # Delivery-Tag zur Queue hinzufügen
                    self.ack_queue.put(method.delivery_tag)
            except Exception as e:
                logger.error(f"Forward-Fehler: {str(e)}")
                self._handle_retry(method, body, properties)

        threading.Timer(delay / 1000, forward_message).start()

    def _handle_retry(self, method, body, properties):
        """Behandelt Wiederholungsversuche"""
        properties.headers = properties.headers or {}
        retries = properties.headers.get('x-retries', 0)

        if retries >= self.retry_config['max_retries']:
            logger.error(f"Max Retries erreicht für: {body[:20]}...")
            return

        def retry_publish():
            try:
                with pika.BlockingConnection(
                        pika.ConnectionParameters(
                            host='rabbitmq',
                            credentials=pika.PlainCredentials('admin', 'admin')
                        )
                ) as conn:
                    channel = conn.channel()
                    new_props = pika.BasicProperties(
                        headers={**properties.headers, 'x-retries': retries + 1},
                        delivery_mode=properties.delivery_mode
                    )
                    channel.basic_publish(
                        exchange='',
                        routing_key=REPLY_QUEUE,
                        body=body,
                        properties=new_props
                    )
            except Exception as e:
                logger.error(f"Retry fehlgeschlagen: {str(e)}")

        base_delay = self.retry_config['base_delay']
        jitter = random.uniform(-self.retry_config['jitter'], self.retry_config['jitter'])
        delay = (2 ** retries) * base_delay + jitter

        logger.warning(f"Retry {retries + 1} in {delay:.2f}ms")
        threading.Timer(delay / 1000, retry_publish).start()

    def start(self):
        """Startet den ResponseProcessor mit Ack-Verarbeitung"""
        while True:
            try:
                self.channel.basic_qos(prefetch_count=50)
                self.channel.basic_consume(
                    queue=REPLY_QUEUE,
                    on_message_callback=self._process_message,
                    auto_ack=False
                )
                logger.info("ResponseProcessor gestartet")

                # Hauptverarbeitungsschleife
                while True:
                    try:
                        # Verarbeite ausstehende Acks
                        delivery_tag = self.ack_queue.get_nowait()
                        self.channel.basic_ack(delivery_tag=delivery_tag)
                    except queue.Empty:
                        # Verarbeite neue Nachrichten
                        self.connection.process_data_events(time_limit=100)

            except (pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker) as e:
                logger.error(f"Verbindungsabbruch: {str(e)}")
                self._reconnect()
                time.sleep(5)

            except pika.exceptions.AMQPChannelError as e:
                logger.error(f"Kanal-Fehler: {str(e)}")
                self._reconnect()
                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("ResponseProcessor gestoppt")
                break

            except Exception as e:
                logger.error(f"Unerwarteter Fehler: {str(e)}")
                time.sleep(10)
                self._reconnect()