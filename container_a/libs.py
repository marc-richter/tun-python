import os
import io
import os
import re
import math
import datetime
from typing import Any, Dict, List, Tuple, Optional

# Matplotlib ohne Display
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def update_channel_yaml_safe(file_path: str, payload: Dict[str, Any], debug: bool = False, sync: str = "none") -> str:
    """
    Nicht-destruktives Update *ohne* os.replace():
      - lädt YAML, setzt NUR Felder aus payload in request_channel/reply_channel
      - schreibt IN-PLACE: f.seek(0) -> write -> f.truncate()
      - kein Rename/Replace (um Hänger auf FUSE/Cloud zu vermeiden)
      - bit_flip bleibt gequotet ("0xFFFF")
    sync: "none" | "flush" | "fsync" (fsync kann auf FUSE/Cloud stark bremsen)
    """
    import yaml
    Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

    class _Dumper(getattr(yaml, "CSafeDumper", yaml.SafeDumper)):
        pass

    def log(msg):
        if debug:
            print(f"[update_channel_yaml_inplace] {msg}", flush=True)

    # ---- Helfer
    def _num(v):
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except Exception:
            return v

    def _hex4(s: Any) -> str:
        try:
            if isinstance(s, str):
                s = s.strip()
                n = int(s, 16) if s.lower().startswith("0x") else int(s, 16)
            else:
                n = int(s)
            return f"0x{(n & 0xFFFF):04X}"
        except Exception:
            return "0x0000"

    class Quoted(str):
        """Immer gequotet dumpen (für '0xFFFF')."""
        pass

    def _represent_quoted(dumper, data):
        return dumper.represent_scalar('tag:yaml.org,2002:str', str(data), style='"')

    _Dumper.add_representer(Quoted, _represent_quoted)

    def _ensure_map(root: Dict[str, Any], key: str) -> Dict[str, Any]:
        cur = root.get(key)
        if not isinstance(cur, dict):
            cur = {} if cur is None else dict(cur) if hasattr(cur, "items") else {}
            root[key] = cur
        return cur

    def _update_channel(dst: Dict[str, Any], ch: Dict[str, Any]) -> None:
        if not isinstance(ch, dict):
            return
        # Basisskalare – nur setzen, wenn geliefert
        if "min_delay_ms" in ch:
            dst["min_delay"] = _num(ch["min_delay_ms"])
        if "max_delay_ms" in ch:
            dst["max_delay"] = _num(ch["max_delay_ms"])
        if "jitter_ms" in ch:
            dst["jitter"] = _num(ch["jitter_ms"])
        if "bit_flip" in ch:
            dst["bit_flip"] = Quoted(_hex4(ch["bit_flip"]))
        if "drop_probability" in ch:
            dst["drop_probability"] = _num(ch["drop_probability"])
        # distribution mergen (nichts löschen)
        if "distribution" in ch:
            d_type = str(ch["distribution"]).lower()
            dmap = _ensure_map(dst, "distribution")
            dmap["type"] = d_type
            params = _ensure_map(dmap, "parameters")
            if d_type == "exponential":
                lam = ch.get("lambda", ch.get("exp_lambda"))
                if lam is not None:
                    params["lambda"] = _num(lam)
            elif d_type == "uniform":
                if "uni_min_ms" in ch:
                    params["min_delay"] = _num(ch["uni_min_ms"])
                if "uni_max_ms" in ch:
                    params["max_delay"] = _num(ch["uni_max_ms"])

    # ---- Laden
    log("A: read YAML")
    if os.path.isdir(file_path):
        raise IsADirectoryError(f"{file_path} ist ein Verzeichnis")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.load(f, Loader=Loader)
    else:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("YAML root ist kein Mapping – Abbruch, um Datenverlust zu vermeiden.")

    req_map = _ensure_map(data, "request_channel")
    rep_map = _ensure_map(data, "reply_channel")
    _update_channel(req_map, payload.get("request_channel", {}))
    _update_channel(rep_map, payload.get("reply_channel", {}))
    # ping_count absichtlich ignoriert

    # ---- Dump in Memory
    log("B: dump YAML")
    dumped = yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
        default_flow_style=False,
    )

    # ---- IN-PLACE schreiben (ohne os.replace)
    log("C: write in-place")
    # existiert -> r+; sonst w+
    mode = "r+" if os.path.exists(file_path) else "w+"
    with open(file_path, mode, encoding="utf-8") as f:
        f.seek(0)
        f.write(dumped)
        # wichtig: alten Rest entfernen, falls neue Datei kürzer ist
        f.truncate()
        if sync in ("flush", "fsync"):
            f.flush()
        if sync == "fsync":
            os.fsync(f.fileno())

    log("D: done")
    return dumped


def parse_ping_messdaten(text: str) -> Dict[str, object]:
    """
    Parst einen (evtl. zusammengeklebten) Ping-Output-Text und liefert:
      - times_ms: Liste der Ping-Zeiten (float, in ms) in Auftrittsreihenfolge
      - seqs:     Liste der icmp_seq (falls vorhanden, sonst aufsteigende Indizes)
      - transmitted: Summe über alle gefundenen "packets transmitted"
      - received:    Summe über alle gefundenen "received"
      - loss_rate:   (transmitted - received)/transmitted (0..1), wenn transmitted>0
      - target:      Ziel-Host aus "PING ..." (letzter gefundener)
    Der Parser ist robust gegenüber mehreren Blöcken (wir sammeln alle Antworten).
    """
    times: List[float] = []
    seqs: List[int] = []
    transmitted_total = 0
    received_total = 0
    target: Optional[str] = None

    # Ziel-Host (letzter PING Header gewinnt)
    for line in text.splitlines():
        m_ping = re.search(r'^PING\s+([^\s(]+)', line.strip())
        if m_ping:
            target = m_ping.group(1)

    # Antworten: ... icmp_seq=K ... time=X ms
    for line in text.splitlines():
        m_time = re.search(r'time[=<]\s*([0-9]*\.?[0-9]+)\s*ms', line)
        if m_time:
            try:
                times.append(float(m_time.group(1)))
            except ValueError:
                pass
        m_seq = re.search(r'icmp_seq=(\d+)', line)
        if m_seq:
            try:
                seqs.append(int(m_seq.group(1)))
            except ValueError:
                pass

    # Summen über alle Statistik-Zeilen
    for line in text.splitlines():
        m_sum = re.search(
            r'(\d+)\s+packets\s+transmitted,\s+(\d+)\s+(?:packets\s+)?received',
            line
        )
        if m_sum:
            transmitted_total += int(m_sum.group(1))
            received_total += int(m_sum.group(2))

    # Fallback, falls keine Summary, aber Antworten da:
    if transmitted_total == 0 and times:
        transmitted_total = len(times)
    if received_total == 0 and times:
        received_total = len(times)

    loss_rate = 0.0
    if transmitted_total > 0:
        loss_rate = max(0.0, min(1.0, (transmitted_total - received_total) / transmitted_total))

    # Wenn keine echten seqs gefunden, Indexspur erzeugen
    if not seqs and times:
        seqs = list(range(1, len(times) + 1))

    return {
        "times_ms": times,
        "seqs": seqs,
        "transmitted": transmitted_total,
        "received": received_total,
        "loss_rate": loss_rate,
        "target": target or "",
    }


# ---------- Helper ----------

def _fig_to_svg_bytes(fig: plt.Figure) -> bytes:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue().encode("utf-8")


def _make_ts(ts: Optional[str] = None) -> str:
    return ts or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _fd_bins(values: List[float]) -> int:
    if len(values) < 2:
        return 1
    xs = sorted(values)
    q1 = xs[int(0.25 * (len(xs) - 1))]
    q3 = xs[int(0.75 * (len(xs) - 1))]
    iqr = q3 - q1
    if iqr <= 0:
        return max(1, int(math.sqrt(len(xs))))
    bw = 2 * iqr / (len(xs) ** (1 / 3))
    span = max(xs) - min(xs)
    if span <= 0 or bw <= 0:
        return max(1, int(math.sqrt(len(xs))))
    return max(1, min(100, int(math.ceil(span / bw))))


# ---------- Bilderzeuger (speichern + SVG-Bytes zurück) ----------

SAVE_DIR = "/var/log/evaluated_data"

def generate_cdf_svg(parsed: Dict[str, object], timestamp: Optional=str) -> Tuple[bytes, str]:
    """
    CDF der Ping-Zeiten (Treppenfunktion, where='post')
    Speichert unter /var/log/evaluated_data/<ts>-cdf.svg
    Rückgabe: (svg_bytes, file_path)
    """
    _ensure_dir(SAVE_DIR)
    ts = _make_ts(timestamp)
    times = list(parsed.get("times_ms", []))  # type: ignore
    target = str(parsed.get("target", "") or "")

    fig, ax = plt.subplots(figsize=(5, 3))
    if times:
        xs = sorted(float(t) for t in times)
        n = len(xs)
        ys = [(i + 1) / n for i in range(n)]
        ax.step(xs, ys, where="post")
        title = "CDF der Ping-Zeiten"
        if target:
            title += f" für {target}"
        ax.set_title(title)
        ax.set_xlabel("Ping-Zeit (ms)")
        ax.set_ylabel("CDF")
        ax.set_ylim(0.0, 1.0)
        ax.grid(True, linestyle=":", linewidth=0.6)
    else:
        ax.set_title("CDF der Ping-Zeiten (keine Daten)")
        ax.axis("off")

    svg = _fig_to_svg_bytes(fig)
    path = os.path.join(SAVE_DIR, f"{ts}-cdf.svg")
    with open(path, "wb") as f:
        f.write(svg)
    return svg, path


def generate_hist_svg(parsed: Dict[str, object], timestamp: Optional=str) -> Tuple[bytes, str]:
    """
    Histogramm/Verteilung der Ping-Zeiten (normiert: relative Häufigkeit)
    Speichert unter /var/log/evaluated_data/<ts>-hist.svg
    Rückgabe: (svg_bytes, file_path)
    """
    _ensure_dir(SAVE_DIR)
    ts = _make_ts(timestamp)
    times = list(parsed.get("times_ms", []))  # type: ignore
    fig, ax = plt.subplots(figsize=(5, 3))

    if times:
        bins = _fd_bins(times)
        # relative Häufigkeit: Gewichte 1/N
        N = len(times)
        weights = [1.0 / N] * N
        ax.hist(times, bins=bins, weights=weights)
        ax.set_title("Verteilung der Ping-Zeiten")
        ax.set_xlabel("Ping-Zeit (ms)")
        ax.set_ylabel("Wahrscheinlichkeit")
        ax.grid(True, axis="y", linestyle=":", linewidth=0.6)
        ymax = max(ax.get_ylim()[1], 0.01)
        ax.set_ylim(0, ymax)
    else:
        ax.set_title("Verteilung der Ping-Zeiten (keine Daten)")
        ax.axis("off")

    svg = _fig_to_svg_bytes(fig)
    path = os.path.join(SAVE_DIR, f"{ts}-hist.svg")
    with open(path, "wb") as f:
        f.write(svg)
    return svg, path


def generate_jitter_svg(parsed: Dict[str, object], timestamp: Optional=str) -> Tuple[bytes, str]:
    """
    Jitter = |Δ time_ms| zwischen aufeinanderfolgenden Pings
    Speichert unter /var/log/evaluated_data/<ts>-jitter.svg
    Rückgabe: (svg_bytes, file_path)
    """
    _ensure_dir(SAVE_DIR)
    ts = _make_ts(timestamp)
    times = list(parsed.get("times_ms", []))  # type: ignore
    seqs  = list(parsed.get("seqs", []))      # type: ignore

    fig, ax = plt.subplots(figsize=(5, 3))
    if times and len(times) >= 2:
        jitters = [abs(times[i] - times[i-1]) for i in range(1, len(times))]
        x = seqs[1:] if seqs and len(seqs) == len(times) else list(range(1, len(times)))
        ax.plot(x, jitters, marker="o")
        mean_j = sum(jitters)/len(jitters)
        ax.set_title(f"Jitter (mean={mean_j:.2f} ms)")
        ax.set_xlabel("icmp_seq (oder Index)")
        ax.set_ylabel("Jitter [ms]")
        ax.grid(True, linestyle=":", linewidth=0.6)
    else:
        ax.set_title("Jitter (keine/zu wenige Daten)")
        ax.axis("off")

    svg = _fig_to_svg_bytes(fig)
    path = os.path.join(SAVE_DIR, f"{ts}-jitter.svg")
    with open(path, "wb") as f:
        f.write(svg)
    return svg, path


def generate_seq_presence_svg(parsed: Dict[str, object],
                              timestamp: Optional[str],
                              ping_count: int) -> Tuple[bytes, str]:
    """
    Präsenzplot NUR für den letzten Ping-Run, mit fixer x-Achse 1..ping_count.

    x: icmp_seq = 1..ping_count
    y: 1 (empfangen) / 0 (fehlt)
    Sequenz-Reset trennt Runs (neuer Run, wenn nächste seq <= vorherige).
    Speichert unter /var/log/evaluated_data/<ts>-seq.svg
    Rückgabe: (svg_bytes, file_path)
    """
    _ensure_dir(SAVE_DIR)
    ts = _make_ts(timestamp)

    seqs = list(parsed.get("seqs", []))          # type: ignore
    times = list(parsed.get("times_ms", []))     # type: ignore

    # ping_count validieren / fallback
    if not isinstance(ping_count, int) or ping_count <= 0:
        # Fallback: versuche aus letztem Run zu schließen, sonst Anzahl times
        if seqs:
            # letztes Segment bestimmen
            runs: List[List[int]] = []
            cur: List[int] = []
            prev = None
            for s in seqs:
                if prev is not None and s <= prev:
                    if cur:
                        runs.append(cur)
                    cur = []
                cur.append(s)
                prev = s
            if cur:
                runs.append(cur)
            last = runs[-1] if runs else []
            ping_count = max(last) if last else len(times) if times else 1
        else:
            ping_count = len(times) if times else 1

    # Letzten Run segmentieren
    present_seq_last_run: set[int] = set()
    if seqs:
        runs = []
        cur = []
        prev = None
        for s in seqs:
            if prev is not None and s <= prev:
                if cur:
                    runs.append(cur)
                cur = []
            cur.append(s)
            prev = s
        if cur:
            runs.append(cur)
        last = runs[-1] if runs else []
        present_seq_last_run = set(last)
    else:
        # Keine icmp_seq gefunden: heuristisch annehmen, dass die ersten len(times)
        # Sequenzen empfangen wurden (1..min(len(times), ping_count))
        present_seq_last_run = set(range(1, min(len(times), ping_count) + 1))

    # Achse 1..ping_count und Präsenzvektor bauen
    xs = list(range(1, ping_count + 1))
    ys = [1 if x in present_seq_last_run else 0 for x in xs]

    # Plotten
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.plot(xs, ys, marker="o")
    ax.set_xlabel("icmp_seq")
    ax.set_ylabel("Empfangen (0/1)")
    if present_seq_last_run:
        smin, smax = min(present_seq_last_run), max(present_seq_last_run)
        ax.set_title(f"Pakete nach Sequenz (letzter Run: {smin}–{smax}, ping_count={ping_count})")
    else:
        ax.set_title(f"Pakete nach Sequenz (keine Daten, ping_count={ping_count})")
    ax.set_yticks([0, 1])
    ax.set_ylim(-0.1, 1.1)
    ax.grid(True, linestyle=":", linewidth=0.6)

    svg = _fig_to_svg_bytes(fig)
    path = os.path.join(SAVE_DIR, f"{ts}-seq.svg")
    with open(path, "wb") as f:
        f.write(svg)
    return svg, path

