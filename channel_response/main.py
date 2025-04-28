from response_processor import ResponseProcessor
import pika
import yaml
import signal
import sys

def shutdown(signum, frame):
    print("\nShutting down...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    with open('channel.yml') as f:
        config = yaml.safe_load(f)

    processor = ResponseProcessor(config)
    processor.start()
