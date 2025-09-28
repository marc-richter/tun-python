import os
from typing import Any, Dict

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


def pictures(messdaten):
    return