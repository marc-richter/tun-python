# common.py
import logging
import struct
from fcntl import ioctl

import pika
from pika.connection import URLParameters

RABBITMQ_HOST = 'amqp://user:pass@rabbitmq:5672/'

REQUEST_QUEUE = 'network_request'
REPLY_QUEUE = 'network_reply'

REQUEST_QUEUE_AFTER_CHANNEL = 'network_request_after_channel'
REPLY_QUEUE_AFTER_CHANNEL = 'network_reply_after_channel'

WEB_QUEUE_UP =  'web_queue_up'
WEB_QUEUE_DOWN = 'web_queue_down'


def get_channel():
    params = URLParameters(RABBITMQ_HOST)  # URLParameters statt ConnectionParameters
    params.socket_timeout = 5
    return pika.BlockingConnection(params).channel()

def open_tun(device_name="tun0"):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA
    ifs = struct.pack("16sH22s", device_name.encode(), LINUX_IFF_TUN | LINUX_IFF_NO_PI, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    logging.info(f"TUN {device_name} initialisiert - FD: {tun.fileno()}")
    return tun
