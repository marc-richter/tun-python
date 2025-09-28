import logging
import pika
import threading
import random
import numpy as np
import queue
import yaml
from common import REQUEST_QUEUE, REQUEST_QUEUE_AFTER_CHANNEL

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RequestProcessor:
    def __init__(self, connection_params, config):
        self.connection_params = connection_params
        self.config = config
        self.ack_queue = queue.Queue()  # Thread-sichere Queue für Acks

    def _calculate_delay(self, params):
        dist_type = params['distribution']['type']
        dist_params = params['distribution']['parameters']

        if dist_type == 'exponential':
            delay = np.random.exponential(dist_params['lambda'])
        elif dist_type == 'normal':
            delay = np.random.normal(dist_params['mu'], dist_params['sigma'])
        elif dist_type == 'uniform':
            delay = random.uniform(params['min_delay'], params['max_delay'])
        else:
            delay = random.uniform(0, params['max_delay'])

        delay += random.uniform(-params['jitter'], params['jitter'])
        return max(params['min_delay'], min(delay, params['max_delay']))

    def _process_packet(self, ch, method, properties, body):
        # hier ggf. die channel.yml neu einlesen
        with open('channel.yml') as f:
             config = yaml.safe_load(f)
        self.config = config                # sicherstellen, dass die neuen channel Parameter auch immer überall bereitgestellt werden
        #params = config['request_channel']
        params = self.config['request_channel']

        if random.random() < params['drop_probability']:
            logger.warning(f"Request verworfen: {body[:20]}...")
            # Kein ACK hier - RabbitMQ wird die Nachricht automatisch neu zustellen
            return

        delay = self._calculate_delay(params)
        logger.info(f"Verzögere Request um {delay:.2f}ms: {body[:20]}...")

        def forward_packet():
            try:
                # Neue Verbindung für die Weiterleitung
                with pika.BlockingConnection(self.connection_params) as conn:
                    channel = conn.channel()
                    channel.basic_publish(
                        exchange='',
                        routing_key=REQUEST_QUEUE_AFTER_CHANNEL,
                        body=body,
                        properties=pika.BasicProperties(
                            headers=properties.headers,
                            delivery_mode=2
                        )
                    )
                    logger.info(f"Request weitergeleitet an {REQUEST_QUEUE_AFTER_CHANNEL}: {body[:20]}...")
                    # Delivery-Tag zur Queue hinzufügen
                    self.ack_queue.put(method.delivery_tag)
            except Exception as e:
                logger.error(f"Fehler beim Weiterleiten des Requests: {str(e)}")

        threading.Timer(delay / 1000, forward_packet).start()

    def start(self):
        with pika.BlockingConnection(self.connection_params) as connection:
            channel = connection.channel()
            channel.queue_declare(
                queue=REQUEST_QUEUE,
                durable=True,
                arguments={'x-queue-type': 'quorum'}
            )
            channel.queue_declare(
                queue=REQUEST_QUEUE_AFTER_CHANNEL,
                durable=True,
                arguments={'x-queue-type': 'quorum'}
            )
            channel.basic_consume(
                queue=REQUEST_QUEUE,
                on_message_callback=self._process_packet
            )
            logger.info("RequestProcessor gestartet")

            while True:
                try:
                    # Verarbeite ausstehende Acks
                    delivery_tag = self.ack_queue.get_nowait()
                    channel.basic_ack(delivery_tag=delivery_tag)
                except queue.Empty:
                    # Verarbeite neue Nachrichten
                    connection.process_data_events(time_limit=100)
