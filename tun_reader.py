import os
import struct
import time
from fcntl import ioctl


def open_tun(device_name):
    tun = open("/dev/net/tun", "r+b", buffering=0)
    LINUX_IFF_TUN = 0x0001
    LINUX_IFF_NO_PI = 0x1000
    LINUX_TUNSETIFF = 0x400454CA

    flags = LINUX_IFF_TUN | LINUX_IFF_NO_PI
    ifs = struct.pack("16sH14s", device_name.encode(), flags, b"")
    ioctl(tun, LINUX_TUNSETIFF, ifs)
    return tun


if __name__ == "__main__":
    try:
        tun = open_tun("tun0")
        # Finale Interface-Konfiguration
        os.system("ip addr flush dev tun0 2>/dev/null")
        os.system("ip addr replace 192.0.2.2/24 dev tun0")
        os.system("ethtool -K tun0 tx off rx off 2>/dev/null")
        os.system("ip link set tun0 up mtu 1500 qlen 500")

        start_time = time.time()
        print("Listening on tun0...")
        while True:
            packet = tun.read(1024)
            if packet:
                print(f"\n[SUCCESS] Received packet ({time.time() - start_time:.2f}s):")
                print(packet.hex())
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nReader stopped")
    finally:
        tun.close()
