#!/bin/bash

##############################################
### TUN-Device Initialisierung (Kernel-Ebene)
###
### Es wird ein TUN-Device mit der IP-Adresse 192.0.2.2 erstellt.
### Das Routing wird so konfiguriert, dass alle Anfragen an IP Adressen aus dem Subnetz 192.0.2.0/24 an das TUN-Device tun0 192.0.2.2  weitergeleitet werden.
### Dh. alle Anfragen an IP-Adressen aus 192.0.2.0/24 außer (192.0.2.0 & 192.0.2.2) werden an das tun0 Device weitergeleitet.
##############################################

# Erstellt Gerätedatei-Struktur für TUN/TAP
mkdir -p /dev/net  # -p: Elternverzeichnisse erzwingen (Kernel erwartet /dev/net)

# Prüft auf existierende Gerätedatei (Character Device) und erstellt sie falls nicht vorhanden
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
# c: Character Device
# 10: Major-Nummer (misc devices)
# 200: Minor-Nr für TUN (kernel.org/Documentation/devices.txt)

# Globaler Zugriff für Testzwecke (Prod: CAP_NET_ADMIN + Gruppenberechtigungen)
chmod 666 /dev/net/tun  # Unsicher, aber für Demos praktisch

#######################################
### Netzwerk-Interface Cleanup
#######################################

# Entfernt Interface aus Kernel-Tabelle, falls vorhanden
ip link del tun0 2>/dev/null || true
sleep 0.5  # Wartet auf Kernel-Cleanup (race condition vermeiden)

###################################
### TUN-Interface Erstellung
###################################

# Kernel-API für TUN/TAP-Devices
ip tuntap add mode tun tun0
# ip tuntap add: Erstellt TUN/TAP-Device
# mode tun: Erstellt ein TUN-Device (Layer 3, arbeitet mit IP-Paketen)
# mode tap: Erstellt ein TAP-Device (Layer 2, arbeitet mit Ethernet-Frames)
# tun0: Name des zu erstellenden TUN-Devices
# Implementierung: drivers/net/tun.c

###################################
### Interface-Konfiguration
###################################
ip addr flush dev tun0 2>/dev/null  # Löscht alle IP-Adressen vom Interface tun0
ip addr replace 192.0.2.2/24 dev tun0  # Weist dem Interface tun0 die IP-Adresse 192.0.2.2/24 zu

###  Optimierungen für Paketdurchsatz

# Deaktiviert ARP-Protokoll für das Interface tun0 (P2P-Verbindung)
ip link set dev tun0 arp off
# dev tun0: Spezifiziert das Netzwerk-Interface tun0
# arp off: Deaktiviert das Address Resolution Protocol (ARP), da es für Punkt-zu-Punkt-Verbindungen nicht benötigt wird

 # Setzt Netzwerkparameter für das Interface tun0
ip link set tun0 up mtu 1500 qlen 500
# up: Aktiviert das Interface tun0
# mtu 1500: Setzt die Maximum Transmission Unit (MTU) auf 1500 Bytes (Standard für Ethernet)
# qlen 500: Setzt die Länge der Übertragungswarteschlange (Transmit Queue Length) auf 500 Pakete

# Deaktiviert Hardware-Offloading
ethtool -K tun0 tx off rx off 2>/dev/null
# Stellt sicher, dass alle Pakete in der CPU im Userspace sind
# Wichtig für Userspace-Paketverarbeitung

################################
### Routing-Konfiguration
################################

# Entfernt die Route für das Subnetz 192.0.2.0/24, falls vorhanden
ip route del 192.0.2.0/24 2>/dev/null || true
# 192.0.2.0/24: Subnetz mit der Netzadresse 192.0.2.0 und der Subnetzmaske 255.255.255.0 (24-Bit-Präfix)
# 2>/dev/null: Unterdrückt Fehlermeldungen, falls die Route nicht existiert
# || true: Verhindert, dass das Skript bei einem Fehler abbricht

# Erstellt oder ersetzt die Route für das Subnetz 192.0.2.0/24
ip route replace 192.0.2.0/24 dev tun0 proto static metric 50
# 192.0.2.0/24: Subnetz mit der Netzadresse 192.0.2.0 und der Subnetzmaske 255.255.255.0 (24-Bit-Präfix)
# dev tun0: Weist das Subnetz dem Interface tun0 zu
# proto static: Gibt an, dass die Route manuell (statisch) hinzugefügt wird
# metric 50: Setzt die Metrik der Route auf 50 (niedrigere Werte haben höhere Priorität)

################################
### Netfilter/Iptables-Regeln
################################
iptables -t nat -F  # Flusht NAT-Tabelle (Vorsicht im Prod!)
iptables -t nat -A POSTROUTING -s 192.0.2.0/24 -j MASQUERADE
# MASQUERADE: Dynamisches NAT (kernel-modul: nf_nat_masquerade_ipv4)

iptables -A FORWARD -i tun0 -o eth0 -j ACCEPT  # Weiterleitung erlauben
iptables -A FORWARD -i eth0 -o tun0 -j ACCEPT
# Kernel-Forwarding muss aktiviert sein (/proc/sys/net/ipv4/ip_forward)

################################
### Pre-Flight Checks
################################
echo "--- Pre-Check ---"
ip link show tun0 | grep -q "state UP" || echo "Interface DOWN!"  # Kernel-Statusabfrage
ping -c 1 192.0.2.1 -I tun0 -W 1 || true  # Bindet an Interface (SO_BINDTODEVICE)
echo "-----------------"

################################
### Prozessstart (Userspace)
################################
# Paketmitschnitt mit Kernel-Buffer
tcpdump -i tun0 -n -v icmp &  # -n: Kein DNS (schneller)
tcpdump_pid=$!

# Python-Anwendung
python3 /app/tun_reader.py -p 253 &
reader_pid=$!

# Warte auf Interface-Initialisierung
sleep 2  # Kernel-Interface kann asynchron sein

# Daten senden
python3 /app/sender.py 192.0.2.1 -i /app/data/img.png

################################
### Cleanup
################################
kill $tcpdump_pid $reader_pid 2>/dev/null  # SIGTERM an Prozesse
wait $reader_pid 2>/dev/null  # Wartet auf korrektes Beenden

echo "=== Final Status ==="
ip -s link show tun0  # Kernel-Statistiken (RX/TX-Pakete, Fehler)
conntrack -L 2>/dev/null | grep 192.0.2 || true  # Connection Tracking
