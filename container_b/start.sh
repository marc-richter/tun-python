#!/bin/bash

### TUN-Device Setup ###
ip link del tun0 2>/dev/null || true
ip tuntap add mode tun tun0
ip addr add 192.0.2.3/24 dev tun0
ip link set tun0 up mtu 1500 qlen 500
ethtool -K tun0 tx off rx off

### Routing ###
ip route replace default dev tun0 metric 20
ip route del 192.0.2.0/24 2>/dev/null || true
ip route add 192.0.2.0/24 dev tun0 proto static metric 60

### Start Writer ###
python3 /app/tun_writer.py
