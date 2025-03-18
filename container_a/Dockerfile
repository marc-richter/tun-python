FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iproute2 \
    python3 \
    python3-pip \
    net-tools \
    iputils-ping \
    curl \
    tcpdump \
    iptables \
    ethtool \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Kopiere alle notwendigen Dateien
COPY common.py .
COPY ./container_a/tun_reader.py .
COPY ./container_a/start.sh .
COPY ./requirements.txt .

RUN pip3 install -r requirements.txt && \
    chmod +x start.sh

CMD ["./start.sh"]
