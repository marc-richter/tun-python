import os
import struct
import time
import numpy as np
from fcntl import ioctl
from scapy.layers.inet import IP, ICMP
from scapy.packet import Raw


def open_tun(device_name):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA

    flags = LINUX_IFF_TUN | LINUX_IFF_NO_PI
    ifs = struct.pack("16sH14s", device_name.encode(), flags, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    return tun


def bytes_to_bitarray(data):
    """Konvertiert Bytes zu einem Numpy-Bitarray"""
    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def format_payload(payload):
    """Formatiert Nutzdaten in String und Hex"""
    try:
        text = payload.decode('utf-8', errors='replace')
    except UnicodeDecodeError:
        text = "[BINARY DATA]"

    hex_str = ' '.join(f"{b:02x}" for b in payload[:16])
    if len(payload) > 16:
        hex_str += " ..."

    return f" Text: {text}\n                       Hex: {hex_str}"


if __name__ == "__main__":
    try:
        tun = open_tun("tun0")
        os.system("ip addr flush dev tun0 2>/dev/null")
        os.system("ip addr replace 192.0.2.2/24 dev tun0")
        os.system("ethtool -K tun0 tx off rx off 2>/dev/null")
        os.system("ip link set tun0 up mtu 1500 qlen 500")

        start_time = time.time()
        print("[TUN READER] Listening on tun0...")

        all_packets_bits = []

        while True:
            raw_packet = tun.read(1024)
            if raw_packet:
                hex_dump = raw_packet.hex()
                bit_array = bytes_to_bitarray(raw_packet)
                all_packets_bits.append(bit_array)

                try:
                    packet = IP(raw_packet)
                    print(f"\n[TUN READER] [SUCCESS] Packet ({time.time() - start_time:.2f}s)")
                    print(f"[TUN READER] Hex Dump: {hex_dump}")

                    if ICMP in packet:
                        icmp = packet[ICMP]
                        print(f"[TUN READER] ICMP Type: {icmp.type}, Code: {icmp.code}")

                        # Payload-Extraktion
                        if Raw in packet:
                            payload = packet[Raw].load
                            print("[TUN READER] Payload:")
                            print(f"[TUN READER]         {format_payload(payload)}")
                        else:
                            print("[TUN READER] Payload: [No payload detected]")

                    print(f"             First 20 Bits: {bit_array[:20]}...")

                except Exception as e:
                    print(f"\n[TUN READER] [RAW PACKET] Error: {str(e)}")
                    print(f"[TUN READER] : {hex_dump}")
                    print(f"[TUN READER] Bits: {bit_array[:20]}...")

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n[TUN READER] Reader stopped")
        print(f"[TUN READER] Gespeicherte Pakete: {len(all_packets_bits)}")
    finally:
        tun.close()
