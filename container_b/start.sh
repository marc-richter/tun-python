#!/bin/bash

### TUN-Device Initialisierung ###
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
chmod 0666 /dev/net/tun

### Alte Interfaces bereinigen ###
ip link del tun0 2>/dev/null || true
sleep 0.5

### Netzwerk-Konfiguration ###
ip tuntap add mode tun tun0
ip addr add 192.0.2.3/24 dev tun0
ip link set tun0 up mtu 1400
ethtool -K tun0 tx off rx off gro off

### Routing optimieren ###
ip route del default 2>/dev/null || true
ip route add 192.0.2.0/24 dev tun0
ip route add default via 192.0.2.1 dev tun0 metric 100
ip route add 172.18.0.0/16 via 172.18.0.1 dev eth0

### Firewall-Regeln ###
iptables -t nat -F
iptables -t nat -A POSTROUTING -o tun0 -j MASQUERADE
iptables -A FORWARD -i tun0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o tun0 -j ACCEPT

### RabbitMQ-Host festlegen ###
echo "172.18.0.2 rabbitmq" >> /etc/hosts

### Service starten ###
python3 /app/tun_writer.py &
writer_pid=$!

### Gesundheitscheck ###
for i in {1..10}; do
    if [ -d /proc/$writer_pid ]; then
        break
    fi
    sleep 1
done

trap "kill $writer_pid; ip link del tun0 2>/dev/null" EXIT
wait $writer_pid
