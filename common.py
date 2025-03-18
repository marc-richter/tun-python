# common.py
import logging
import struct
from fcntl import ioctl

import pika

RABBITMQ_HOST = 'rabbitmq'
REQUEST_QUEUE = 'network_request'
REPLY_QUEUE = 'network_reply'

def get_channel():
    params = pika.ConnectionParameters(host=RABBITMQ_HOST)
    connection = pika.BlockingConnection(params)
    return connection.channel()

def open_tun(device_name="tun0"):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA
    ifs = struct.pack("16sH22s", device_name.encode(), LINUX_IFF_TUN | LINUX_IFF_NO_PI, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    logging.info(f"TUN-Interface {device_name} initialisiert")
    return tun