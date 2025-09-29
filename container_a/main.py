#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py
-------
Backend-Brücke zwischen RabbitMQ (AMQP) und deinem Web/Headless-Client.

Funktion:
- Verbindung zu RabbitMQ herstellen.
- Nachrichten von 'web_queue_down' (Web -> Python) konsumieren.
- Auf Typen reagieren:
    * "request_initial": channel.yml einlesen und als "initial_values" zurücksenden.
    * "start_simulation": Platzhalter-Funktion start_simulation(payload) aufrufen.
    * "stop_simulation":  stop_simulation() -> beendet Prozess/Verbindung sauber.
- Antworten an 'web_queue_up' (Python -> Web) publizieren.
"""
import datetime
import json
import os
import shutil
import sys
import time
import signal
import threading
from pathlib import Path
import subprocess
from libs import (
    update_channel_yaml_safe,
    parse_ping_messdaten,
    generate_cdf_svg,
    generate_hist_svg,
    generate_jitter_svg,
    generate_seq_presence_svg
)

import pika     # AMQP-Client für RabbitMQ
import yaml     # YAML-Parser für das Einlesen von channel.yml
#from IPython.testing.tools import printed_msg

# =========================
#   Konfiguration
# =========================
# Die Verbindungsdaten können über Umgebungsvariablen überschrieben werden.
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", "5672"))
RABBIT_USER = os.getenv("RABBIT_USER", "admin")
RABBIT_PASS = os.getenv("RABBIT_PASS", "admin")

# Queues
QUEUE_DOWN = os.getenv("QUEUE_DOWN", "web_queue_down")  # Web/GUI -> Python
QUEUE_UP   = os.getenv("QUEUE_UP",   "web_queue_up")    # Python -> Web/GUI

# Pfad zur Kanal-Konfiguration
CHANNEL_YML_PATH = os.getenv("CHANNEL_YML_PATH", "channel.yml")

# Globale Verbindungsobjekte
_connection = None
_channel = None
_shutdown = threading.Event()


# =========================
#   Utils (Hilfsfunktionen)
# =========================
def _publish_up_svg(svg_data, headers=None):
    """
    Hilfsfunktion: Sendet ein einzelnes SVG an die Up-Queue.
    - svg_data: bytes oder str (SVG-XML)
    - headers: optionale AMQP-Header (dict), z.B. {"chart": "cdf"}
    """
    try:
        if isinstance(svg_data, str):
            body = svg_data.encode("utf-8")
        elif isinstance(svg_data, (bytes, bytearray)):
            body = bytes(svg_data)
        else:
            raise TypeError("svg_data muss bytes oder str sein")

        _channel.basic_publish(
            exchange="",
            routing_key=QUEUE_UP,
            body=body,
            properties=pika.BasicProperties(
                content_type="image/svg+xml",
                headers=headers or {},
            ),
        )
    except Exception as e:
        print(f"[PY] Fehler beim Publish (SVG): {e}", flush=True)


def pictures(messdaten: str, ping_count):
    """
    Nimmt den rohen Ping-Output (messdaten), parst ihn und erzeugt drei SVGs:
      - CDF
      - Histogramm/Verteilung
      - Jitter
    Jede Bildfunktion speichert selbst unter /var/log/evaluated_data/<TS>-*.svg
    und liefert SVG-Bytes zurück, die wir direkt ans GUI senden.
    """
    parsed = parse_ping_messdaten(messdaten)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        svg_cdf, _ = generate_cdf_svg(parsed, ts)
        _publish_up_svg(svg_cdf, headers={"chart": "cdf"})          # image/svg+xml
    except Exception as e:
        _publish_up_svg({"type": "log", "text": f"CDF-Fehler: {e}"})

    try:
        svg_hist, _ = generate_hist_svg(parsed, ts)
        _publish_up_svg(svg_hist, headers={"chart": "hist"})
    except Exception as e:
        _publish_up_svg({"type": "log", "text": f"Histogramm-Fehler: {e}"})

    try:
        svg_jitter, _ = generate_jitter_svg(parsed, ts)
        _publish_up_svg(svg_jitter, headers={"chart": "jitter"})
    except Exception as e:
        _publish_up_svg({"type": "log", "text": f"Jitter-Fehler: {e}"})

    try:
        svg_seq, _ = generate_seq_presence_svg(parsed, ts, ping_count)
        _publish_up_svg(svg_seq, headers={"chart": "seq"})  # nutzt deine bestehende SVG-Publish-Funktion
    except Exception as e:
        _publish_up({"type": "log", "text": f"SEQ-Plot-Fehler: {e}"})



def _hexify_bit_flip(val):
    """
    Normalisiert den 'bit_flip'-Wert aus der YAML-Konfiguration zu einem Hex-String "0x..".
    """
    if isinstance(val, str):
        s = val.strip().lower()
        if s.startswith("0x"):
            return s
        try:
            n = int(s)
            return hex(n)
        except Exception:
            pass
    if isinstance(val, (int, float)):
        return hex(int(val))
    return "0x0"


def _normalize_channel_block(d: dict) -> dict:
    """
    Normalisiert ein Kanal-Config-Dict:
      - Benennt Keys in erwartete Namen um (min_delay_ms, max_delay_ms, jitter_ms, ...)
      - Erzwingt float/int-Typen, falls sinnvoll
    """
    d = d or {}
    out = {}

    # Delay / Jitter
    for src, dst in [
        ("min_delay_ms", "min_delay_ms"),
        ("min_delay",    "min_delay_ms"),
        ("max_delay_ms", "max_delay_ms"),
        ("max_delay",    "max_delay_ms"),
        ("jitter_ms",    "jitter_ms"),
        ("jitter",       "jitter_ms"),
    ]:
        if src in d and d[src] is not None:
            try:
                out[dst] = float(d[src])
            except Exception:
                pass

    # Bit-Flip
    for src in ("bit_flip", "bit_error", "bit_error_rate"):
        if src in d and d[src] is not None:
            try:
                out["bit_flip"] = float(d[src])
            except Exception:
                out["bit_flip"] = 0.0
            break

    # Drop-Probability
    for src in ("drop_probability", "drop_prob", "drop"):
        if src in d and d[src] is not None:
            try:
                out["drop_probability"] = float(d[src])
            except Exception:
                out["drop_probability"] = 0.0
            break

    # Distribution
    dist = d.get("distribution") or d.get("dist") or "exponential"
    dist = str(dist).lower()
    if dist not in ("exponential", "uniform"):
        dist = "exponential"
    out["distribution"] = dist

    if dist == "exponential":
        lam = d.get("lambda") or d.get("exp_lambda") or 1.0
        try:
            out["lambda"] = float(lam)
        except Exception:
            out["lambda"] = 1.0
    else:
        umin = d.get("uni_min_ms") or d.get("uniform_min_ms") or d.get("uniform_min") or 0.0
        umax = d.get("uni_max_ms") or d.get("uniform_max_ms") or d.get("uniform_max") or 0.0
        try:
            out["uni_min_ms"] = float(umin)
        except Exception:
            out["uni_min_ms"] = 0.0
        try:
            out["uni_max_ms"] = float(umax)
        except Exception:
            out["uni_max_ms"] = 0.0

    return out


# =========================
#   Config laden/aufbereiten
# =========================
def load_channel_config(path=CHANNEL_YML_PATH) -> dict:
    """
    Lädt die Kanal-Parameter aus der YAML-Datei (z. B. channel.yml).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {p.resolve()}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    req = _normalize_channel_block(data.get("request_channel", {}))
    rep = _normalize_channel_block(data.get("reply_channel", {}))

    return {
        "request_channel": req,
        "reply_channel": rep,
    }


def make_initial_values_message(cfg: dict) -> dict:
    """
    Antwort-Nachricht für das Frontend auf 'request_initial'.
    Formatiert für GUI.py:
        {
          "type": "channel_config",
          "payload": {
             "forward": {...},
             "reverse": {...}
          }
        }
    """
    # Aus cfg die beiden Blöcke holen; akzeptiere vorhandene Keys
    req = cfg.get("request_channel", {})
    rep = cfg.get("reply_channel", {})
    # In 'forward'/'reverse' umbenennen, damit GUI.py sie direkt erkennt
    return {
        "type": "channel_config",
        "payload": {
            "forward": req,
            "reverse": rep,
        },
    }


# =========================
#   RabbitMQ I/O (Transport)
# =========================
def _connect():
    """
    Stellt die Verbindung zu RabbitMQ her und deklariert die benötigten Queues.

    WICHTIG (NEU):
    - heartbeat=120  → verhindert Verbindungsabbrüche bei kurzzeitig blockierendem Code,
                       da Broker erst nach 120 s ausbleibender Heartbeats trennt.
    """
    global _connection, _channel
    creds = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
    params = pika.ConnectionParameters(
        host=RABBIT_HOST,
        port=RABBIT_PORT,
        virtual_host="/",
        credentials=creds,
        heartbeat=120,                 # <-- größerer Heartbeat (vorher ~30 s)
        blocked_connection_timeout=300 # großzügiger Timeout für blockierte I/O
    )
    _connection = pika.BlockingConnection(params)
    _channel = _connection.channel()

    # Durable kann optional aktiviert werden (Queue überlebt Broker-Neustart):
    # durable=True; beachte dann auch persistent publish (delivery_mode=2)
    _channel.queue_declare(queue=QUEUE_DOWN, durable=True, auto_delete=False)
    _channel.queue_declare(queue=QUEUE_UP,   durable=True, auto_delete=False)

    # Begrüßungs-Log an Up-Queue
    msg = {"type": "log", "text": f"Python-Backend verbunden: {RABBIT_HOST}:{RABBIT_PORT}"}
    body = json.dumps(msg)
    _channel.basic_publish(
        exchange="",
        routing_key=QUEUE_UP,
        body=body.encode("utf-8"),
        properties=pika.BasicProperties(content_type="application/json"),
    )
    print(f"[PY] -> {QUEUE_UP}: {msg.get('type')}", flush=True)



def ping_os_start(params: dict) -> str:
    print("Ping Funktion Py gestartet", flush=True)
    target = "192.0.2.3"
    iface = "tun0"
    ping_count = int(params.get("ping_count", 1))
    per_packet_timeout_sec = "2"

    # ping-Binary sicher finden
    #ping_bin = shutil.which("ping") or "/bin/ping"
    #print("Baue Ping command zusammen", flush=True)
    cmd = [
        "ping",
        "-c", str(ping_count),
        "-W", per_packet_timeout_sec,   # Linux: Timeout je Paket (Sekunden)
        "-I", iface,                    # Linux: Interface
        target,
    ]
    #print("1", flush=True)
    log_dir = "/var/log/container_a"
    log_path = os.path.join(log_dir, "ping_neu.log")
    os.makedirs(log_dir, exist_ok=True)
    #print("2", flush=True)
    header = f"=== {datetime.datetime.now().isoformat(timespec='seconds')} | {' '.join(cmd)} ===\n"
    output_lines = []

    print("Starte Ping", flush=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f, \
             subprocess.Popen(
                 cmd,
                 stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT,
                 text=True,            # = universal_newlines=True
                 bufsize=1             # zeilengepuffert
             ) as proc:

            f.write(header)
            # Zeile für Zeile lesen -> gleichzeitig loggen & sammeln
            for line in proc.stdout:
                output_lines.append(line)
                f.write(line)

            # sicherstellen, dass der Prozess auch beendet ist
            proc.wait()

    except FileNotFoundError:
        line = "Error: 'ping' command not found on system PATH.\n"
        output_lines.append(line)
        # trotzdem loggen
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(header + line)
        except Exception:
            pass
    except Exception as e:
        line = f"Error executing ping: {e}\n"
        output_lines.append(line)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(header + line)
        except Exception:
            pass

    output = "".join(output_lines)
    return output

def write_channel_params():
    return


# =========================
#   Simulation-Hooks (Platzhalter)
# =========================
def start_simulation(payload: dict):
    """
    Platzhalter-Funktion, die aufgerufen wird, wenn das Web-Frontend
      - die Nachricht {"type":"start_simulation", "payload": {...}} sendet.
      - request_channel (dict)
      - reply_channel   (dict)
      - ping_count      (int, optional)

    Hier kannst du später Threads starten, Messungen durchführen, SVGs erzeugen
    und an QUEUE_UP senden, etc.
    """

    print("[PY] Simulation START mit Parametern:", payload, flush=True)

    # Kanalparameter in channel.yml schreiben
    print(
        update_channel_yaml_safe(
            "channel.yml",
            payload,
            debug=True,
            sync="none"  # kein fsync -> keine FUSE/Cloud-Hänger
        ),
        flush=True
    )


    messdaten = ping_os_start(payload)
    print(messdaten, flush=True)
    print("Ping Funktion beendet.", flush=True)

    #TODO: Messdaten auswerten
    pictures(messdaten,int(payload.get("ping_count", 1)))

    #for i in range(ping_count):
    #    _publish_up({"type": "log", "text": f"Ping {i+1}/{ping_count}"})
    #    time.sleep(0.2)
    print("Simulation beendet.")
    _publish_up({"type": "log", "text": "Simulation fertig."})


def stop_simulation():
    """
    Beendet sauber:
    - Stoppt die Consumer-Schleife
    - Schließt die Verbindung
    - Beendet den Prozess
    """
    print("[PY] Simulation STOP ausgelöst. Schließe Verbindung und beende Programm.", flush=True)

    try:
        if _channel and _channel.is_open:
            _channel.stop_consuming()
        if _connection and _connection.is_open:
            _connection.close()
    except Exception as e:
        print(f"[PY] Fehler beim Beenden: {e}", flush=True)

    _shutdown.set()
    sys.exit(0)


def _publish_up(payload: dict):
    """
    Hilfsfunktion: Sendet JSON an die Up-Queue.
    """
    try:
        _channel.basic_publish(
            exchange="",
            routing_key=QUEUE_UP,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(content_type="application/json"),
        )
    except Exception as e:
        print(f"[PY] Fehler beim Publish: {e}", flush=True)


# =========================
#   Consumer-Loop (Hauptlogik)
# =========================
def wait_for_request_and_respond_with_channel_data():
    """
    Konsumiert Nachrichten von 'web_queue_down' und reagiert auf:
      - request_initial  -> YAML laden, initial_values an web_queue_up
      - start_simulation -> start_simulation(payload)
      - stop_simulation  -> stop_simulation()
    """
    print("[PY] Warte auf Nachrichten …", flush=True)

    def _on_message(ch, method, properties, body: bytes):
        # Hinweis: Callbacks kurz halten -> verhindert Heartbeat-Blockaden.
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception:
            print("[PY] Ungültige Nachricht (kein JSON) – ignoriert.", flush=True)
            # ack im finally
            msg = None

        # Routing
        try:
            if not msg:
                return

            mtype = msg.get("type")
            print(f"[PY] <- {QUEUE_DOWN}: {mtype}", flush=True)

            if mtype == "request_initial":
                cfg = load_channel_config()
                _publish_up(make_initial_values_message(cfg))
                print("Initial Request beantwortet.")

            elif mtype == "start_simulation":
                print("Simulation wird gestartet.")
                start_simulation(msg.get("payload", {}))

            elif mtype == "stop_simulation":
                # WICHTIG: vor sys.exit() ack senden, sonst wird die Nachricht erneut zugestellt
                ch.basic_ack(delivery_tag=method.delivery_tag)
                stop_simulation()
                return

            else:
                _publish_up({"type": "log", "text": f"Unbekannter Typ: {mtype}"})

        except Exception as e:
            _publish_up({"type": "log", "text": f"Fehler: {e}"})

        finally:
            # Nachricht nur dann ack'en, wenn wir NICHT gerade in stop_simulation() aussteigen
            if _channel and _channel.is_open and not _shutdown.is_set():
                try:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"[PY] Konnte Nachricht nicht bestätigen: {e}", flush=True)

    # Enges QoS vermeidet lange Callback-Laufzeiten mit vielen unbestätigten Messages
    _channel.basic_qos(prefetch_count=1)
    _channel.basic_consume(queue=QUEUE_DOWN, on_message_callback=_on_message, auto_ack=False)

    try:
        _channel.start_consuming()
    except KeyboardInterrupt:
        pass


def start_rabbit():
    """
    Startet:
    - RabbitMQ-Verbindung (mit Heartbeat=120s)
    - Schickt initiale Log-Zeile
    - Startet Consumer-Loop
    """
    global _connection, _channel

    _connect()

    _publish_up({"type": "log", "text": "Backend bereit. Sende 'request_initial', um Konfiguration zu laden."})

    wait_for_request_and_respond_with_channel_data()


def _graceful_shutdown(*_args):
    """
    Signal-Handler für SIGINT/SIGTERM – schließt Verbindung und beendet Prozess.
    """
    global _connection
    _shutdown.set()
    try:
        if _connection and _connection.is_open:
            _connection.close()
    except Exception:
        pass
    sys.exit(0)


# =========================
#   Programmeinstieg
# =========================
if __name__ == "__main__":
    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    print("Python skript main.py gestartet.")
    start_rabbit()
