# tun_writer.py

import logging

from common import get_channel, REQUEST_QUEUE, REPLY_QUEUE, open_tun

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')


def process_incoming(ch, method, properties, body):
    with open_tun() as tun:
        tun.write(body)
        logging.info(f"Paket an TUN gesendet: {len(body)} bytes")

        # Antwort aus TUN lesen
        response = tun.read(65535)
        if response:
            channel.basic_publish(
                exchange='',
                routing_key=REPLY_QUEUE,
                body=response
            )


if __name__ == "__main__":
    channel = get_channel()
    channel.basic_consume(
        queue=REQUEST_QUEUE,
        on_message_callback=process_incoming,
        auto_ack=True
    )
    channel.start_consuming()
