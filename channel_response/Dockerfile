FROM ubuntu:22.04
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgomp1 \
    iproute2 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Alle benötigten Dateien kopieren
COPY ./channel_response/main.py ./requirements.txt ./common.py ./channel.yml *.py /app/
COPY ./channel_response/response_processor.py /app/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5672

# Hauptskript für parallelen Start verwenden
CMD ["python3", "main.py"]
