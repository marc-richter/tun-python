FROM ubuntu:22.04

# Setze korrekte Architektur
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture amd64

# Repository mit korrekter Architektur
RUN sed -i 's/ports.ubuntu.com/archive.ubuntu.com/g' /etc/apt/sources.list

# Pakete mit stabilen Repositories installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    iproute2 \
    python3 \
    python3-pip \
    net-tools \
    iputils-ping \
    curl \
    tcpdump \
    iptables \
    ethtool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


# Kopiere alle notwendigen Dateien
COPY common.py .
COPY ./container_b/tun_writer.py .
COPY ./container_b/start.sh .
COPY ./requirements.txt .

RUN pip3 install -r requirements.txt && \
    chmod +x start.sh

CMD ["./start.sh"]
