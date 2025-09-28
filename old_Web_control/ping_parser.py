import re
import json
import datetime
from pathlib import Path

def extract_ping_block(text: str) -> str:
    pattern = re.compile(r"(PING .*? ping statistics ---.*?ms)", re.S)
    match = pattern.search(text)
    if match:
        return match.group(1)
    return ""

def parse_ping_output(ping_output: str) -> dict:
    result = {"target": {}, "replies": [], "statistics": {}}
    lines = ping_output.strip().splitlines()

    # Kopfzeile
    header_re = re.compile(
        r"PING\s+(?P<hostname>[^\s]+)\s+\((?P<ip>[\d.]+)\)\s+from\s+(?P<src>[\d.]+)\s+(?P<iface>\w+):\s+(?P<bytes>\d+)\((?P<total_bytes>\d+)\)"
    )
    if lines and (m := header_re.match(lines[0])):
        result["target"] = {
            "hostname": m.group("hostname"),
            "ip": m.group("ip"),
            "source_ip": m.group("src"),
            "interface": m.group("iface"),
            "bytes": int(m.group("bytes")),
            "total_bytes": int(m.group("total_bytes")),
        }

    # Antworten
    reply_re = re.compile(
        r"icmp_seq=(?P<seq>\d+)\s+ttl=(?P<ttl>\d+)\s+time=(?P<time>[\d.]+)\s*ms"
    )
    for line in lines:
        if m := reply_re.search(line):
            result["replies"].append({
                "icmp_seq": int(m.group("seq")),
                "ttl": int(m.group("ttl")),
                "time_ms": float(m.group("time"))
            })

    # Statistik
    stats_re = re.compile(
        r"(?P<tx>\d+)\s+packets transmitted,\s+(?P<rx>\d+)\s+received,\s+(?P<loss>\d+)% packet loss,\s+time\s+(?P<time>\d+)ms"
    )
    for line in lines:
        if m := stats_re.search(line):
            result["statistics"] = {
                "transmitted": int(m.group("tx")),
                "received": int(m.group("rx")),
                "loss_percent": int(m.group("loss")),
                "total_time_ms": int(m.group("time"))
            }

    return result

def process_ping_file(input_file: str, output_dir: str = ".") -> dict:
    text = Path(input_file).read_text(encoding="utf-8", errors="ignore")
    ping_block = extract_ping_block(text)
    if not ping_block:
        raise ValueError("Kein Ping-Block gefunden!")

    parsed = parse_ping_output(ping_block)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outfile = Path(output_dir) / f"ping_{timestamp}.json"
    outfile.write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    return parsed
