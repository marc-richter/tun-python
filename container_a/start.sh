#!/bin/bash

### TUN-Device Initialisierung ###
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
chmod 0666 /dev/net/tun

### Netzwerk-Konfiguration ###
ip link del tun0 2>/dev/null || true
ip tuntap add mode tun tun0
ip addr add 192.0.2.2/24 dev tun0   # IP des Tun Interfaces
ip link set tun0 up mtu 1400
ethtool -K tun0 tx off rx off gro off

### Routing optimieren ###
ip route replace default via 192.0.2.1 dev tun0 metric 100
ip route add 172.18.0.0/16 via 172.18.0.1 dev eth0

### Firewall-Regeln ###
iptables -t nat -F
iptables -t nat -A POSTROUTING -o tun0 -j MASQUERADE
iptables -A FORWARD -i tun0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o tun0 -j ACCEPT
### Firewall-Anpassungen ###
iptables -A INPUT -i tun0 -j ACCEPT
iptables -A OUTPUT -o tun0 -j ACCEPT
iptables -t nat -A POSTROUTING -s 192.0.2.0/24 -j MASQUERADE
iptables -A INPUT -i tun0 -p icmp --icmp-type 0 -j ACCEPT
iptables -A OUTPUT -o tun0 -p icmp --icmp-type 8 -j ACCEPT



### RabbitMQ-Host festlegen ###
echo "172.18.0.2 rabbitmq" >> /etc/hosts

### Service starten ###
python3 /app/tun_reader.py &
reader_pid=$!

sleep 3  # Warte auf Interface-Initialisierung
#########################################################################################

### Ping-Test mit korrekter Route ###
#echo "Ping test startet"
#ping -c 1 192.0.2.3 -I tun0 -W 2 &> /var/log/container_a/ping_test.log
#cat /var/log/container_a/ping_test.log

# TODO: hier die Main Routine aufrufen
python3 /app/main.py &
#cat /var/log/container_a/ping_test.log

# TODO: IPERF-Test ausprobieren


#########################################################################################

trap "kill $reader_pid; ip link del tun0 2>/dev/null" EXIT
wait $reader_pid
