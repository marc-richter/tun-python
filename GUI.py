#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PySide6-GUI: Zwei unabhängige Kanal-Parameter (Hin/Rück), RabbitMQ-Statuskreis und SVG-Anzeige (max. 4).

Wichtig: Alle RabbitMQ-Operationen laufen in Threads (kein Blocking im GUI-Thread):
- UpConsumer (RECEIVE_QUEUE) zeigt SVG/JSON an.
- PublisherWorker (SEND_QUEUE) verbindet/sendet asynchron (Buttons & Initial-Request).

Buttons über dem SVG-Bereich:
- „Simulation starten“ -> {"type":"start_simulation","payload":{"request_channel":Hin,"reply_channel":Rück, "ping_count": <SpinBox>}}
- „Simulation stoppen“ -> {"type":"stop_simulation"}

Bit-Flip:
- Wird unabhängig je Kanal editiert.
- Anzeige/Eingabe als Hex `0xFFFF` (4-stellig, Großbuchstaben).

Neu:
- Start-Button wird GELB (disabled) nach Senden; wird GRÜN (enabled), wenn "Simulation fertig." empfangen wurde.
"""

# ---------------------------- Konfiguration -----------------------------------
RABBIT_HOST = "127.0.0.1"
RABBIT_PORT = 5672
RABBIT_VHOST = "/"
RABBIT_USERNAME = "admin"   # ggf. anpassen
RABBIT_PASSWORD = "admin"   # ggf. anpassen

# Down-Queue (GUI -> main.py): hier sendet das GUI Anfragen/Kommandos
SEND_QUEUE = "web_queue_down"
# Up-Queue   (main.py -> GUI): hier empfängt das GUI SVGs und JSON-Antworten
RECEIVE_QUEUE = "web_queue_up"

HEARTBEAT = 30
BLOCKING_TIMEOUT = 120
CONFIG_REQUEST_PAYLOADS = [
    {"type": "request_initial"},        # bevorzugt
    {"type": "get_channel_config"},
    {"request": "channel_config"},
]
CONFIG_KEYS_FORWARD = ("forward", "fwd", "hin", "uplink", "tx", "up", "a", "channel_up", "ch_up")
CONFIG_KEYS_REVERSE = ("reverse", "rev", "rueck", "downlink", "rx", "down", "b", "channel_down", "ch_down")
# -------------------------------------------------------------------------------

import json
import sys
import threading
import logging
from collections import deque
from typing import List, Optional, Tuple, Dict, Any
import queue
import time
import re

import pika
from pika.exceptions import ChannelClosedByBroker
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtSvgWidgets import QSvgWidget

from GUI_libs import starte_backend, stop_backend


# ---------------------------- Logging mit Ringpuffer ----------------------------
class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        self.buffer.append(msg)

    def get_text(self) -> str:
        return "\n".join(self.buffer)


logger = logging.getLogger("amqp_gui")
logger.setLevel(logging.INFO)
_ring = RingBufferHandler(2000)
_ring.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_ring)
# ------------------------------------------------------------------------------


# ---------------------------- kleine Hex-Helfer ----------------------------
_HEX_RE = re.compile(r"^0x[0-9A-Fa-f]{1,4}$")

def normalize_hex4(val: Any) -> str:
    """
    Normalisiert val zu '0xFFFF' (4-stellig, uppercase).
    Erlaubt Eingaben wie '0x1a', '1A', 26, etc.
    Fallback: '0x0000'
    """
    if isinstance(val, str):
        s = val.strip()
        if s.startswith(("0x", "0X")):
            s = s.lower()
            if _HEX_RE.match(s):
                n = int(s, 16)
                return f"0x{n:04X}"
            try:
                n = int(s, 16)
                return f"0x{n:04X}"
            except Exception:
                return "0x0000"
        # reine Hex ohne 0x?
        try:
            n = int(s, 16)
            return f"0x{n:04X}"
        except Exception:
            # ggf. dezimal?
            try:
                n = int(float(s))
                return f"0x{n & 0xFFFF:04X}"
            except Exception:
                return "0x0000"
    if isinstance(val, (int, float)):
        n = int(val)
        return f"0x{n & 0xFFFF:04X}"
    return "0x0000"
# ------------------------------------------------------------------------------


# ---------------------------- Netzwerk-Parameter Modell ----------------------------
class NetParams(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.min_delay_ms: float = 0.0
        self.max_delay_ms: float = 0.0
        self.jitter_ms: float = 0.0
        # WICHTIG: Bit-Flip jetzt als Hex-String (4-stellig)
        self.bit_flip: str = "0x0000"
        self.drop_probability: float = 0.0
        self.distribution: str = "exponential"  # "exponential" | "uniform"
        self.exp_lambda: float = 1.0            # nur exponential
        self.uni_min_ms: float = 0.0            # nur uniform
        self.uni_max_ms: float = 0.0            # nur uniform

    def update(self, **kwargs):
        dirty = False
        for k, v in kwargs.items():
            if k == "bit_flip":
                v = normalize_hex4(v)
            if hasattr(self, k) and getattr(self, k) != v:
                setattr(self, k, v)
                dirty = True
        if dirty:
            self.changed.emit()

    def assign_from_dict(self, d: Dict[str, Any]):
        """Robustes Mapping von Dict auf Felder (ms und Wahrscheinlichkeiten erwartet)."""
        def _get(*names, default=None):
            for n in names:
                if n in d and d[n] is not None:
                    return d[n]
            return default

        dist = _get("distribution", "dist", default=self.distribution)
        if dist not in ("exponential", "uniform"):
            dist = self.distribution

        # Bit-Flip zuerst lesen & normalisieren (akzeptiert hex-string oder numerisch)
        bf_in = _get("bit_flip", "bit_error", "bit_error_rate", default=self.bit_flip)
        bf_hex = normalize_hex4(bf_in)

        vals = {
            "min_delay_ms": float(_get("min_delay_ms", "min_delay", "min_ms", "min", default=self.min_delay_ms)),
            "max_delay_ms": float(_get("max_delay_ms", "max_delay", "max_ms", "max", default=self.max_delay_ms)),
            "jitter_ms": float(_get("jitter_ms", "jitter", default=self.jitter_ms)),
            "bit_flip": bf_hex,  # jetzt als Hex-String
            "drop_probability": float(_get("drop_probability", "drop_prob", "drop", default=self.drop_probability)),
            "distribution": dist,
        }
        if dist == "exponential":
            lam = _get("lambda", "exp_lambda", default=self.exp_lambda)
            try:
                vals["exp_lambda"] = float(lam)
            except Exception:
                vals["exp_lambda"] = self.exp_lambda
        else:
            umin = _get("uni_min_ms", "uniform_min_ms", "uniform_min", default=self.uni_min_ms)
            umax = _get("uni_max_ms", "uniform_max_ms", "uniform_max", default=self.uni_max_ms)
            if "uniform" in d and isinstance(d["uniform"], dict):
                umin = d["uniform"].get("min_ms", umin)
                umax = d["uniform"].get("max_ms", umax)
            try:
                vals["uni_min_ms"] = float(umin)
                vals["uni_max_ms"] = float(umax)
            except Exception:
                vals["uni_min_ms"] = self.uni_min_ms
                vals["uni_max_ms"] = self.uni_max_ms

        self.update(**vals)

    def to_payload_dict(self) -> dict:
        """Format, das main.py (start_simulation) versteht – bit_flip als Hex-String."""
        d = {
            "min_delay_ms": self.min_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "jitter_ms": self.jitter_ms,
            "bit_flip": self.bit_flip,  # Hex-String "0xFFFF"
            "drop_probability": self.drop_probability,
            "distribution": self.distribution,
        }
        if self.distribution == "exponential":
            d["lambda"] = self.exp_lambda
        else:
            d["uni_min_ms"] = self.uni_min_ms
            d["uni_max_ms"] = self.uni_max_ms
        return d
# ------------------------------------------------------------------------------


# ---------------------------- Hilfen für Config-Splitting ----------------------------
def split_channel_config(cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Extrahiert Forward/Reverse aus einer Config, unterstützt mehrere Key-Varianten."""
    if isinstance(cfg, list) and cfg:
        fwd = next((c for c in cfg if str(c.get("type","")).lower() in ("forward","fwd","hin","uplink","tx","up","a")), None)
        rev = next((c for c in cfg if str(c.get("type","")).lower() in ("reverse","rev","rueck","downlink","rx","down","b")), None)
        return fwd, rev

    if not isinstance(cfg, dict):
        return None, None

    for kf in CONFIG_KEYS_FORWARD:
        for kr in CONFIG_KEYS_REVERSE:
            if kf in cfg or kr in cfg:
                return cfg.get(kf), cfg.get(kr)

    if "channels" in cfg and isinstance(cfg["channels"], list):
        return split_channel_config(cfg["channels"])

    for kf in ("channel_up", "ch_up"):
        for kr in ("channel_down", "ch_down"):
            if kf in cfg or kr in cfg:
                return cfg.get(kf), cfg.get(kr)

    return cfg, cfg
# ------------------------------------------------------------------------------


# ---------------------------- Rabbit Client (re-used in threads) ----------------------------
class RabbitClient:
    """Dünner Wrapper um pika.BlockingConnection für eine Queue-Paar-Nutzung."""

    def __init__(self):
        self._params = pika.ConnectionParameters(
            host=RABBIT_HOST,
            port=RABBIT_PORT,
            virtual_host=RABBIT_VHOST,
            heartbeat=HEARTBEAT,
            blocked_connection_timeout=BLOCKING_TIMEOUT,
            credentials=pika.PlainCredentials(RABBIT_USERNAME, RABBIT_PASSWORD),
            connection_attempts=3,
            retry_delay=2,
        )
        self._conn: Optional[pika.BlockingConnection] = None
        self._ch: Optional[pika.adapters.blocking_connection.BlockingChannel] = None

    def connect(self) -> bool:
        if self._conn and self._conn.is_open and self._ch and self._ch.is_open:
            return True
        logger.info("RabbitClient: Verbinde zu %s:%s ...", RABBIT_HOST, RABBIT_PORT)
        self._conn = pika.BlockingConnection(self._params)
        self._ch = self._conn.channel()
        # passiver Check vermeidet Durable-Konflikte
        self._ch.queue_declare(queue=SEND_QUEUE, passive=True)
        return True

    def publish_json(self, payload: dict) -> None:
        assert self._ch is not None
        self._ch.basic_publish(
            exchange="",
            routing_key=SEND_QUEUE,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        )

    def is_connected(self) -> bool:
        return bool(self._conn and self._conn.is_open and self._ch and self._ch.is_open)

    def close(self):
        try:
            if self._ch and self._ch.is_open:
                self._ch.close()
        finally:
            if self._conn and self._conn.is_open:
                self._conn.close()
# ------------------------------------------------------------------------------


# ---------------------------- PublisherWorker (Thread, non-blocking UI) ----------------------------
class PublisherWorker(QtCore.QThread):
    connectionChanged = QtCore.Signal(bool)
    error = QtCore.Signal(str)
    sent = QtCore.Signal(str)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._q: "queue.Queue[dict]" = queue.Queue()
        self._client = RabbitClient()
        self._connected = False

    def run(self) -> None:
        while not self._stop.is_set():
            # Stelle Verbindung sicher, wenn nicht verbunden
            if not self._connected:
                try:
                    self._client.connect()
                    self._connected = True
                    self.connectionChanged.emit(True)
                    logger.info("PublisherWorker: verbunden.")
                except Exception as exc:
                    if self._connected:
                        self._connected = False
                        self.connectionChanged.emit(False)
                    logger.exception("PublisherWorker: connect fehlgeschlagen: %s", exc)
                    self.error.emit(f"Publisher: {exc}")
                    # Backoff
                    for _ in range(20):  # ~2s
                        if self._stop.is_set():
                            break
                        time.sleep(0.1)
                    continue

            # Nachrichten aus Queue verarbeiten
            try:
                payload = self._q.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if not self._connected:
                    # falls in der Zwischenzeit getrennt, nochmal Verbindung versuchen
                    self._client.connect()
                    self._connected = True
                    self.connectionChanged.emit(True)
                self._client.publish_json(payload)
                t = str(payload.get("type", ""))
                self.sent.emit(t)
                logger.info("PublisherWorker: gesendet (%s).", t)
            except Exception as exc:
                logger.exception("PublisherWorker: publish fehlgeschlagen: %s", exc)
                self.error.emit(f"Publisher: {exc}")
                # Verbindung als down markieren -> nächster Loop versucht Reconnect
                if self._connected:
                    self._connected = False
                    self.connectionChanged.emit(False)
                # kurze Pause um Spin zu vermeiden
                time.sleep(0.5)

    def send(self, payload: dict) -> None:
        """Thread-safe enqueue."""
        self._q.put(payload)

    def stop(self) -> None:
        self._stop.set()
        # Queue wecken, damit der Thread schnell aussteigt
        self._q.put({"type": "__quit__"})
        self.wait(2000)
        self._client.close()
# ------------------------------------------------------------------------------


# ---------------------------- Consumer (Up-Queue) ----------------------------
class UpConsumer(QtCore.QThread):
    """
    Konsumiert Nachrichten aus RECEIVE_QUEUE.
    - SVGs -> signal svgReceived(bytes)
    - JSON-Config/Log -> signal configReceived(dict)
    """
    svgReceived = QtCore.Signal(bytes)
    configReceived = QtCore.Signal(dict)
    error = QtCore.Signal(str)
    connectionChanged = QtCore.Signal(bool)

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._params = pika.ConnectionParameters(
            host=RABBIT_HOST,
            port=RABBIT_PORT,
            virtual_host=RABBIT_VHOST,
            heartbeat=HEARTBEAT,
            blocked_connection_timeout=BLOCKING_TIMEOUT,
            credentials=pika.PlainCredentials(RABBIT_USERNAME, RABBIT_PASSWORD),
            connection_attempts=3,
            retry_delay=2,
        )

    def run(self) -> None:
        while not self._stop.is_set():
            conn = None
            ch = None
            try:
                logger.info("Consumer: Verbinde zu RabbitMQ %s:%s ...", RABBIT_HOST, RABBIT_PORT)
                conn = pika.BlockingConnection(self._params)
                ch = conn.channel()
                ch.queue_declare(queue=RECEIVE_QUEUE, passive=True)
                ch.basic_qos(prefetch_count=1)
                logger.info("Consumer: Verbindung ok, Queue '%s' vorhanden.", RECEIVE_QUEUE)
                self.connectionChanged.emit(True)

                for msg in ch.consume(RECEIVE_QUEUE, inactivity_timeout=1.0, auto_ack=False):
                    if self._stop.is_set():
                        break
                    if msg is None:
                        continue
                    method, props, body = msg
                    if method is None or body is None:
                        continue

                    try:
                        handled = False
                        ctype = getattr(props, "content_type", None) if props else None
                        head = body[:256].lstrip().lower()

                        if ctype and "svg" in ctype:
                            self.svgReceived.emit(body)
                            logger.info("Consumer: SVG empfangen (%d Bytes).", len(body))
                            handled = True
                        elif (ctype and "json" in ctype) or head.startswith(b"{") or head.startswith(b"["):
                            try:
                                data = json.loads(body.decode("utf-8"))
                                if isinstance(data, dict):
                                    self.configReceived.emit(data)
                                    logger.info("Consumer: JSON empfangen: keys=%s", list(data.keys()))
                                    handled = True
                                elif isinstance(data, list):
                                    self.configReceived.emit({"channels": data})
                                    logger.info("Consumer: JSON-Liste empfangen (len=%d).", len(data))
                                    handled = True
                            except Exception as je:
                                logger.error("Consumer: JSON parse error: %s", je)

                        if not handled and b"<svg" in head:
                            self.svgReceived.emit(body)
                            logger.info("Consumer: SVG (heuristisch) empfangen (%d Bytes).", len(body))
                            handled = True

                        if not handled:
                            logger.info("Consumer: Unbekannte Nachricht ignoriert (len=%d).", len(body))
                    finally:
                        try:
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                        except Exception:
                            break

            except ChannelClosedByBroker as ccb:
                code, text = getattr(ccb, "reply_code", None), getattr(ccb, "reply_text", str(ccb))
                self.error.emit(f"Consumer-Queue '{RECEIVE_QUEUE}' nicht nutzbar (Code {code}): {text}")
                logger.error("Consumer: Queue '%s' nicht nutzbar (Code %s): %s", RECEIVE_QUEUE, code, text)
            except Exception as exc:
                self.error.emit(f"RabbitMQ-Fehler: {exc}")
                logger.exception("Consumer: RabbitMQ-Fehler: %s", exc)
            finally:
                self.connectionChanged.emit(False)
                try:
                    if ch and ch.is_open:
                        ch.close()
                        logger.info("Consumer: Channel geschlossen.")
                finally:
                    if conn and conn.is_open:
                        conn.close()
                        logger.info("Consumer: Verbindung geschlossen.")

            # kurzer Backoff vor Reconnect
            for _ in range(20):
                if self._stop.is_set():
                    break
                time.sleep(0.1)

    def stop(self) -> None:
        self._stop.set()
# ------------------------------------------------------------------------------


# ---------------------------- UI-Helfer: Status-Kreis & Log-Dialog ----------------------------
class StatusDot(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, diameter: int = 14, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._ok = False
        self._d = diameter
        self.setFixedSize(self._d, self._d)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("AMQP-Verbindung (Klick für Logs)")

    def set_ok(self, ok: bool):
        if self._ok != ok:
            self._ok = ok
            self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        color = QtGui.QColor(0, 180, 0) if self._ok else QtGui.QColor(200, 0, 0)
        p.setBrush(color)
        p.setPen(QtGui.QPen(QtGui.QColor(60, 60, 60), 1))
        p.drawEllipse(rect)


class LogDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verbindungs-Logs")
        self.resize(720, 420)
        layout = QtWidgets.QVBoxLayout(self)

        self.text = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.text.setFont(font)
        layout.addWidget(self.text, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("Aktualisieren")
        self.btn_copy = QtWidgets.QPushButton("Alles kopieren")
        self.btn_close = QtWidgets.QPushButton("Schließen")
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.btn_refresh.clicked.connect(self.reload)
        self.btn_copy.clicked.connect(self.copy_all)
        self.btn_close.clicked.connect(self.accept)

        self.reload()

    def reload(self):
        self.text.setPlainText(_ring.get_text())
        self.text.moveCursor(QtGui.QTextCursor.End)

    def copy_all(self):
        self.text.selectAll()
        self.text.copy()
# ----------------------------------------------------------------------------------------------


# ---------------------------- Parameter-Zeile (UI) ----------------------------
class ParamRow:
    """Eine Zeile mit Widgets, die an ein eigenes NetParams-Modell gebunden sind."""
    def __init__(self, name: str, model: NetParams, grid: QtWidgets.QGridLayout, row: int):
        self.model = model

        # Kanal-Label (erste Spalte)
        self.name_label = QtWidgets.QLabel(f"<b>{name}</b>")
        self.name_label.setAlignment(QtCore.Qt.AlignCenter)

        # Editor-Widgets
        self.min_delay = self._spin_ms()
        self.max_delay = self._spin_ms()
        self.jitter = self._spin_ms()

        # BIT-FLIP: Hex-Edit mit Validator
        self.bit_flip = QtWidgets.QLineEdit()
        self.bit_flip.setPlaceholderText("0x0000")
        self.bit_flip.setText("0x0000")
        rx = QtCore.QRegularExpression(r"^0x[0-9A-Fa-f]{0,4}$")
        self.bit_flip.setValidator(QtGui.QRegularExpressionValidator(rx))
        # Einheitliches Monospace für bessere Lesbarkeit
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.bit_flip.setFont(mono)
        self.bit_flip.setMaximumWidth(100)

        self.drop_prob = self._spin_prob()
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(["exponential", "uniform"])

        # Zusatzfelder
        self.exp_lambda = self._spin_generic(minv=0.0, maxv=1e9, step=0.001, decimals=6, suffix="")
        self.uni_min = self._spin_ms()
        self.uni_max = self._spin_ms()

        # In Grid einfügen
        col = 0
        grid.addWidget(self.name_label, row, col); col += 1
        grid.addWidget(self.min_delay, row, col); col += 1
        grid.addWidget(self.max_delay, row, col); col += 1
        grid.addWidget(self.jitter, row, col); col += 1
        grid.addWidget(self.bit_flip, row, col); col += 1
        grid.addWidget(self.drop_prob, row, col); col += 1
        grid.addWidget(self.combo, row, col); col += 1
        grid.addWidget(self.exp_lambda, row, col); col += 1
        grid.addWidget(self.uni_min, row, col); col += 1
        grid.addWidget(self.uni_max, row, col); col += 1

        # Editor -> Modell
        self.min_delay.valueChanged.connect(lambda v: self.model.update(min_delay_ms=float(v)))
        self.max_delay.valueChanged.connect(lambda v: self.model.update(max_delay_ms=float(v)))
        self.jitter.valueChanged.connect(lambda v: self.model.update(jitter_ms=float(v)))

        # Bit-Flip: bei Edit-Ende normalisieren + ins Modell schreiben
        self.bit_flip.editingFinished.connect(self._commit_bitflip)

        self.drop_prob.valueChanged.connect(lambda v: self.model.update(drop_probability=float(v)))
        self.combo.currentTextChanged.connect(self._on_dist_changed)
        self.exp_lambda.valueChanged.connect(lambda v: self.model.update(exp_lambda=float(v)))
        self.uni_min.valueChanged.connect(lambda v: self.model.update(uni_min_ms=float(v)))
        self.uni_max.valueChanged.connect(lambda v: self.model.update(uni_max_ms=float(v)))

        # Modell -> Editor
        self.model.changed.connect(self.refresh_from_model)
        self.refresh_from_model()

    # Spinner-Fabriken
    def _spin_ms(self) -> QtWidgets.QDoubleSpinBox:
        return self._spin_generic(minv=0.0, maxv=1e9, step=0.1, decimals=3, suffix=" ms")

    def _spin_prob(self) -> QtWidgets.QDoubleSpinBox:
        return self._spin_generic(minv=0.0, maxv=1.0, step=0.0001, decimals=6, suffix="")

    def _spin_generic(self, minv: float, maxv: float, step: float, decimals: int, suffix: str) -> QtWidgets.QDoubleSpinBox:
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(minv, maxv)
        sb.setDecimals(decimals)
        sb.setSingleStep(step)
        sb.setSuffix(suffix)
        sb.setMinimumWidth(110)
        sb.setAlignment(QtCore.Qt.AlignRight)
        return sb

    def _on_dist_changed(self, txt: str):
        self.model.update(distribution=txt)
        self._update_visibility()

    def _commit_bitflip(self):
        text = self.bit_flip.text().strip()
        norm = normalize_hex4(text)
        if text != norm:
            # Signal kurz blocken, um Feedbackschleifen zu vermeiden
            blocker = QtCore.QSignalBlocker(self.bit_flip)
            self.bit_flip.setText(norm)
            del blocker
        self.model.update(bit_flip=norm)

    def refresh_from_model(self):
        widgets = [self.min_delay, self.max_delay, self.jitter, self.drop_prob,
                   self.exp_lambda, self.uni_min, self.uni_max, self.combo, self.bit_flip]
        blockers = [QtCore.QSignalBlocker(w) for w in widgets]

        self.min_delay.setValue(self.model.min_delay_ms)
        self.max_delay.setValue(self.model.max_delay_ms)
        self.jitter.setValue(self.model.jitter_ms)

        # Bit-Flip in Hex anzeigen
        self.bit_flip.setText(normalize_hex4(self.model.bit_flip))

        self.drop_prob.setValue(self.model.drop_probability)

        idx = self.combo.findText(self.model.distribution)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

        self.exp_lambda.setValue(self.model.exp_lambda)
        self.uni_min.setValue(self.model.uni_min_ms)
        self.uni_max.setValue(self.model.uni_max_ms)

        del blockers
        self._update_visibility()

    def _update_visibility(self):
        is_exp = (self.model.distribution == "exponential")
        self.exp_lambda.setVisible(is_exp)
        self.uni_min.setVisible(not is_exp)
        self.uni_max.setVisible(not is_exp)
# ------------------------------------------------------------------------------


class SvgTile(QtWidgets.QFrame):
    """Kachel-Widget, das ein SVG anzeigen kann."""
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(220, 160)

        self._svg_widget = QSvgWidget(self)
        self._svg_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._svg_widget, 1)

    def set_svg_bytes(self, data: bytes) -> None:
        ba = QtCore.QByteArray(data) if data else QtCore.QByteArray()
        self._svg_widget.load(ba)
# ------------------------------------------------------------------------------


class MainWindow(QtWidgets.QMainWindow):
    MAX_IMAGES = 4

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RabbitMQ SVG Dashboard (Qt)")
        self.resize(1200, 740)

        # Zentrales Widget & Layouts
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Topbar mit Status-Kreis (rechts)
        topbar = QtWidgets.QHBoxLayout()
        topbar.addStretch(1)
        self.status_dot = StatusDot(diameter=14)
        self.status_dot.clicked.connect(self.show_logs)
        topbar.addWidget(self.status_dot, alignment=QtCore.Qt.AlignRight)
        root.addLayout(topbar)

        # ---------------- Netzwerk-Parameter (zwei UNABHÄNGIGE Zeilen) ----------------
        params_box = QtWidgets.QGroupBox("Netzwerk-Parameter")
        params_grid = QtWidgets.QGridLayout(params_box)
        params_grid.setContentsMargins(10, 10, 6, 6)
        params_grid.setHorizontalSpacing(8)
        params_grid.setVerticalSpacing(6)

        headers = [
            "Kanal",
            "min_delay [ms]",
            "max_delay [ms]",
            "jitter [ms]",
            "bit_flip",
            "drop_probability",
            "distribution",
            "lambda",
            "uni_min [ms]",
            "uni_max [ms]",
        ]
        for c, text in enumerate(headers):
            lbl = QtWidgets.QLabel(f"<b>{text}</b>")
            params_grid.addWidget(lbl, 0, c, alignment=QtCore.Qt.AlignCenter)

        self.net_params_fwd = NetParams()  # Hin-Kanal
        self.net_params_rev = NetParams()  # Rück-Kanal

        self.row_fwd = ParamRow("Hin-Kanal", self.net_params_fwd, params_grid, row=1)
        self.row_rev = ParamRow("Rück-Kanal", self.net_params_rev, params_grid, row=2)

        root.addWidget(params_box)
        # ------------------------------------------------------------------------------

        # ---------------- Steuer-Buttons (über dem SVG-Bereich) ----------------
        btn_bar = QtWidgets.QHBoxLayout()

        # Feld "Anzahl Pakete" links vom Start-Button
        lbl_pkts = QtWidgets.QLabel("Anzahl Pakete:")
        self.spin_ping_count = QtWidgets.QSpinBox()
        self.spin_ping_count.setRange(1, 1_000_000_000)
        self.spin_ping_count.setValue(10)
        self.spin_ping_count.setMinimumWidth(100)

        self.btn_start = QtWidgets.QPushButton("Simulation starten")
        self.btn_stop  = QtWidgets.QPushButton("Simulation stoppen")
        self.btn_start.clicked.connect(self.on_start_simulation)
        self.btn_stop.clicked.connect(self.on_stop_simulation)

        btn_bar.addWidget(lbl_pkts)
        btn_bar.addWidget(self.spin_ping_count)
        btn_bar.addSpacing(12)
        btn_bar.addWidget(self.btn_start)
        btn_bar.addWidget(self.btn_stop)
        btn_bar.addStretch(1)
        root.addLayout(btn_bar)
        # ----------------------------------------------------------------------

        # SVG Grid (2x2)
        grid_box = QtWidgets.QGroupBox(f"Empfangene SVGs (max. {self.MAX_IMAGES})")
        grid = QtWidgets.QGridLayout(grid_box)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.tiles: List[SvgTile] = []
        for r in range(2):
            for c in range(2):
                tile = SvgTile()
                grid.addWidget(tile, r, c)
                self.tiles.append(tile)
        root.addWidget(grid_box, 1)

        # Statuszeile
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

        # Puffer der letzten 4 SVGs (Bytes)
        self._svg_buffer: List[bytes] = []

        # Verbindungsstatusflags
        self._consumer_connected = False
        self._publisher_connected = False

        # ---------- Threads starten ----------
        self.pub_worker = PublisherWorker(self)
        self.pub_worker.connectionChanged.connect(self.on_pub_connection_changed)
        self.pub_worker.error.connect(self.on_error)
        # NEU: Sent-Signal auswerten, um Button gelb zu setzen und zu sperren
        self.pub_worker.sent.connect(self.on_pub_message_sent)
        self.pub_worker.start()

        self.consumer = UpConsumer(self)
        self.consumer.svgReceived.connect(self.on_svg_received)
        self.consumer.configReceived.connect(self.on_config_received)
        self.consumer.error.connect(self.on_error)
        self.consumer.connectionChanged.connect(self.on_consumer_connection_changed)
        self.consumer.start()

        # --- Initiale Config anfordern (non-blocking: nur enqueue) ---
        self._config_requested = False
        self._request_timer = QtCore.QTimer(self)
        self._request_timer.setInterval(3000)  # 3 s
        self._request_timer.timeout.connect(self._enqueue_config_request)
        self._enqueue_config_request()
        if not self._config_requested:
            self._request_timer.start()

        self.update_connection_dot()

    # ---------------- RabbitMQ / Config-Flow ----------------
    def _enqueue_config_request(self):
        payload = CONFIG_REQUEST_PAYLOADS[0]
        self.pub_worker.send(payload)
        logger.info("GUI: Konfigurationsanfrage enqueued.")
        self._config_requested = True
        self._request_timer.stop()

    @QtCore.Slot(dict)
    def on_config_received(self, data: dict):
        # NEU: Reagiere auf Log "Simulation fertig."
        if isinstance(data, dict) and data.get("type") == "log":
            text = str(data.get("text", ""))
            if "Simulation fertig" in text:
                self.btn_start.setEnabled(True)
                self.btn_start.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; }")
            return

        cfg = (
            data.get("payload")
            or data.get("data")
            or data.get("config")
            or data.get("channel_config")
            or data
        )
        fwd, rev = split_channel_config(cfg)
        if fwd:
            try:
                self.net_params_fwd.assign_from_dict(fwd)
            except Exception as exc:
                logger.exception("GUI: Fehler beim Anwenden Forward-Config: %s", exc)
        if rev:
            try:
                self.net_params_rev.assign_from_dict(rev)
            except Exception as exc:
                logger.exception("GUI: Fehler beim Anwenden Reverse-Config: %s", exc)
        self.status.showMessage("Kanal-Konfiguration empfangen und übernommen.", 3000)

    @QtCore.Slot(str)
    def on_pub_message_sent(self, type_str: str):
        """Wird vom PublisherWorker emittiert, nachdem eine Nachricht veröffentlicht wurde."""
        if type_str == "start_simulation":
            # Gelb + gesperrt bis "Simulation fertig." empfangen wird
            self.btn_start.setEnabled(False)
            self.btn_start.setStyleSheet("QPushButton { background-color: #f1c40f; color: black; }")

    # ---------------- Start/Stop Simulation ----------------
    def on_start_simulation(self):
        """Sammelt die aktuellen Kanalwerte und sendet start_simulation."""
        request_channel = self.net_params_fwd.to_payload_dict()  # Hin-Kanal
        reply_channel   = self.net_params_rev.to_payload_dict()  # Rück-Kanal
        msg = {
            "type": "start_simulation",
            "payload": {
                "request_channel": request_channel,
                "reply_channel": reply_channel,
                "ping_count": int(self.spin_ping_count.value()),
            },
        }
        self.pub_worker.send(msg)
        self.status.showMessage("start_simulation gesendet (queued).", 2500)

    def on_stop_simulation(self):
        """Sendet stop_simulation."""
        self.pub_worker.send({"type": "stop_simulation"})
        try:
            stop_backend(down_with_volumes=False)
        except Exception as e:
            self.log(f"Backend-Stop-Fehler: {e}")
        self.status.showMessage("stop_simulation gesendet (queued).", 2500)

    # ---------------- SVG-Flow ----------------
    @QtCore.Slot(bytes)
    def on_svg_received(self, data: bytes) -> None:
        if len(self._svg_buffer) >= self.MAX_IMAGES:
            self._svg_buffer.pop(0)
        self._svg_buffer.append(data)
        for tile in self.tiles:
            tile.set_svg_bytes(b"")
        for i, svg_bytes in enumerate(self._svg_buffer):
            self.tiles[i].set_svg_bytes(svg_bytes)
        self.status.showMessage("SVG empfangen.", 1500)

    # ---------------- Sonstiges ----------------
    @QtCore.Slot(bool)
    def on_consumer_connection_changed(self, ok: bool):
        self._consumer_connected = ok
        self.update_connection_dot()

    @QtCore.Slot(bool)
    def on_pub_connection_changed(self, ok: bool):
        self._publisher_connected = ok
        self.update_connection_dot()

    @QtCore.Slot(str)
    def on_error(self, msg: str) -> None:
        self.status.showMessage(msg, 5000)

    def update_connection_dot(self):
        is_ok = self._publisher_connected or self._consumer_connected
        self.status_dot.set_ok(is_ok)

    def show_logs(self):
        LogDialog(self).exec()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            if hasattr(self, "consumer"):
                self.consumer.stop()
                self.consumer.wait(1500)
            if hasattr(self, "pub_worker"):
                self.pub_worker.stop()
        finally:
            super().closeEvent(event)













if __name__ == "__main__":

    starte_backend()

    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
