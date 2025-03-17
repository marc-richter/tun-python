#!/bin/bash

### Globales Routing-Setup ###
# Deaktiviere bestehende Default-Route
ip route del default 2>/dev/null || true

### TUN-Device Initialisierung ###
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
chmod 666 /dev/net/tun

# Cleanup
ip link del tun0 2>/dev/null || true
sleep 0.5

# Neues TUN-Device erstellen
ip tuntap add mode tun tun0
ip addr flush dev tun0
ip addr add 192.0.2.2/24 dev tun0
ip link set tun0 up mtu 1500 qlen 500
ethtool -K tun0 tx off rx off

### Kritische Routing-Änderungen ###
# 1. Setze TUN0 als Standardroute
ip route replace default dev tun0 metric 10

# 2. Blockiere direktes Routing über physische Interfaces
ip route del 192.0.2.0/24 2>/dev/null || true
ip route add 192.0.2.0/24 dev tun0 proto static metric 50


### Iptables Regeln ###
iptables -t nat -F
iptables -t nat -A POSTROUTING -o tun0 -j MASQUERADE
iptables -A FORWARD -i tun0 -j ACCEPT
iptables -A FORWARD -o tun0 -j ACCEPT
iptables -t nat -A POSTROUTING -s 192.0.2.0/24 -j MASQUERADE
# In start.sh nach NAT-Regeln einfügen
iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.0.2.2:8080
iptables -A FORWARD -p tcp --dport 8080 -j ACCEPT



### Starte Reader ###
python3 /app/tun_reader.py &
reader_pid=$!

# Warte auf Initialisierung
sleep 2

### Testkommunikation ###
ping -c 1 1.1.1.1 -I tun0 -W 5 || true

curl --interface tun0 http://1.1.1.1:8080/hello-world || true

### Cleanup-Handler ###
trap "kill $reader_pid; ip link del tun0" EXIT
