#!/bin/bash

# TUN-Device Setup
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
chmod 666 /dev/net/tun

# Cleanup alte Interfaces
ip link del tun0 2>/dev/null || true
sleep 0.5

# Neues TUN-Interface erstellen
ip tuntap add mode tun tun0

# Interface-Konfiguration
ip addr flush dev tun0 2>/dev/null
ip addr replace 192.0.2.2/24 dev tun0
ip link set dev tun0 arp off
ip link set tun0 up mtu 1500 qlen 500
ethtool -K tun0 tx off rx off 2>/dev/null
sleep 2

# Routing konfigurieren
ip route del 192.0.2.0/24 2>/dev/null || true
ip route replace 192.0.2.0/24 dev tun0 proto static metric 50

# Iptables-Regeln
iptables -t nat -F
iptables -t nat -A POSTROUTING -s 192.0.2.0/24 -j MASQUERADE
iptables -A FORWARD -i tun0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o tun0 -j ACCEPT

# Pre-Checks
echo "--- Pre-Check ---"
ip link show tun0 | grep -q "state UP" || echo "Interface DOWN!"
ping -c 1 192.0.2.1 -I tun0 -W 1 || true
echo "-----------------"

# Prozesse starten
tcpdump -i tun0 -n -v icmp &
tcpdump_pid=$!

python3 /app/tun_reader.py &
reader_pid=$!

sleep 2
python3 /app/sender.py

# Cleanup
kill $tcpdump_pid $reader_pid 2>/dev/null
wait $reader_pid 2>/dev/null

echo "=== Final Status ==="
ip -s link show tun0
conntrack -L 2>/dev/null | grep 192.0.2 || true
