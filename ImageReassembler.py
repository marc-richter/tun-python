import io
import logging
import os
import time
from collections import defaultdict

from PIL import Image

logging.basicConfig(level=logging.INFO,
                    format='%(filename)-15s - %(asctime)s - %(levelname)s - %(message)s')

class ImageReassembler:
    def __init__(self):
        self.image_buffers = defaultdict(bytes)
        self.last_received = defaultdict(float)
        self.timeout = 5

    def add_packet(self, src_ip, data):
        if data == b"END_OF_IMAGE":
            self.save_image(src_ip)
            return True
        self.image_buffers[src_ip] += data
        self.last_received[src_ip] = time.time()
        return False

    def save_image(self, src_ip):
        data = self.image_buffers.get(src_ip)
        if not data:
            logging.error(f"Keine Daten zum Speichern von {src_ip}")
            return

        directory = "/app/data/received"
        os.makedirs(directory, exist_ok=True)
        filename = os.path.join(directory, f"received_{src_ip}_{int(time.time())}.png")
        try:
            # Konvertiere die Rohdaten in ein Pillow Image-Objekt
            image = Image.open(io.BytesIO(data))
            # Speichere das Bild im PNG-Format
            image.save(filename, format="PNG")
            logging.info(f"Bild gespeichert: {filename} ({len(data)} bytes)")
            del self.image_buffers[src_ip]
            del self.last_received[src_ip]
        except Exception as e:
            logging.error(f"Speicherfehler {filename}: {str(e)}")