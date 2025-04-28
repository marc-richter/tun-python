from request_processor import RequestProcessor
import pika
import yaml
import threading

with open('channel.yml') as f:
    config = yaml.safe_load(f)

connection_params = pika.ConnectionParameters(
    host='rabbitmq',
    credentials=pika.PlainCredentials('admin', 'admin'),
    heartbeat=60,
    blocked_connection_timeout=120,
    connection_attempts=5,
    retry_delay=10
)

def run_processor(processor):
    try:
        processor.start()
    except Exception as e:
        print(f"Processor error: {str(e)}")

if __name__ == "__main__":
    request_processor = RequestProcessor(connection_params, config)

    request_processor.start()

    # Halte Hauptthread aktiv
    while True:
        pass
