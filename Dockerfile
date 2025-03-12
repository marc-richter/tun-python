FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iproute2 \
    python3 \
    python3-pip \
    net-tools \
    iputils-ping \
    tcpdump \
    iptables \
    ethtool \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install scapy
RUN pip3 install scapy numpy


COPY *.py /app/
COPY start.sh /app/

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
