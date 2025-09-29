# libs.py (Ergänzung)

# Modulweiter Zustand: erlaubt späteres Stoppen
_BACKEND = {
    "up_proc": None,        # Popen-Objekt von `docker compose up --build`
    "compose_dir": None,    # Path zum Ordner mit docker-compose.yml
}

def starte_backend():
    """
    Startet das Docker-Backend:
      1) docker compose down -v
      2) docker compose up --build   (Output live)
    Blockiert bis im Output die Zeile mit 'Warte auf Nachrichten' auftaucht.
    Danach läuft 'up' weiter; ein Hintergrund-Thread streamt weiterhin die Logs.
    """
    import sys, subprocess, threading
    from pathlib import Path

    # -------------------- Helper --------------------
    def _find_compose_dir(start: Path) -> Path:
        # Suche docker-compose.yml vom start-Verzeichnis nach oben
        for p in [start, *start.parents]:
            if (p / "docker-compose.yml").exists():
                return p
        # Fallback: aktuelles Verzeichnis
        return start

    def _run_and_stream(cmd: list[str], cwd: Path):
        # Führt ein Kommando aus und streamt stdout/stderr live auf die Konsole
        print(f"[BOOT] $ {' '.join(cmd)}  (cwd={cwd})", flush=True)
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
        return proc.returncode

    def _pump_logs(proc: subprocess.Popen):
        # Pumpt die restlichen Logs, damit der Prozess nicht blockiert
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
        except Exception:
            pass
        finally:
            try:
                proc.wait(timeout=1)
            except Exception:
                pass

    def _compose_cmd(subcmd: list[str]) -> list[str]:
        # Bevorzugt 'docker compose', fällt auf 'docker-compose' zurück
        # (Wir probieren einfach 'docker compose' zuerst.)
        cmd = ["docker", "compose", *subcmd]
        try:
            # Schnelltest: ruft nur die Hilfe auf – wenn es das Kommando nicht gibt, wirft Popen später.
            return cmd
        except Exception:
            return ["docker-compose", *subcmd]

    # -------------------- Setup --------------------
    start_dir = Path.cwd()
    compose_dir = _find_compose_dir(start_dir)

    # -------------------- down -v --------------------
    rc = _run_and_stream(_compose_cmd(["down", "-v"]), compose_dir)
    if rc != 0:
        raise RuntimeError(f"'docker compose down -v' fehlgeschlagen (rc={rc})")

    # -------------------- up --build (attach) --------------------
    up_cmd = _compose_cmd(["up", "--build"])
    print(f"[BOOT] $ {' '.join(up_cmd)}  (cwd={compose_dir})", flush=True)
    up_proc = subprocess.Popen(
        up_cmd,
        cwd=str(compose_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        errors="replace",
    )
    assert up_proc.stdout is not None

    # Sentinel: Diese Teil-Textstelle reicht, um Unicode-Varianten ('…' vs '...') robust zu treffen
    SENTINEL_SUBSTR = "Warte auf Nachrichten"

    sentinel_seen = False
    try:
        # Lies Zeilen, gib sie 1:1 aus, bis der Sentinel kommt
        for line in up_proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if SENTINEL_SUBSTR in line:
                sentinel_seen = True
                break
    except Exception:
        # Falls Lesen scheitert, Prozessstatus prüfen
        pass

    if not sentinel_seen:
        # Prozess evtl. schon beendet? Rest puffern und prüfen
        try:
            # lese noch anstehende Daten (falls vorhanden)
            remainder = up_proc.stdout.read()
            if remainder:
                sys.stdout.write(remainder)
                sys.stdout.flush()
        except Exception:
            pass

        # Wenn der Prozess jetzt bereits beendet ist, ist das ein Fehlerfall
        if up_proc.poll() is not None and not sentinel_seen:
            raise RuntimeError("docker compose up --build endete, bevor 'Warte auf Nachrichten' erschien.")

        # Der Prozess läuft weiter, aber Sentinel kam noch nicht – blockierend weiter einlesen
        for line in up_proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if SENTINEL_SUBSTR in line:
                sentinel_seen = True
                break

        if not sentinel_seen:
            raise RuntimeError("Sentinel 'Warte auf Nachrichten' wurde nicht gefunden.")

    # Ab hier: Sentinel gesehen → Logs weiter in einem Thread pumpen,
    # damit 'up' angehängt bleibt und nicht wegen vollem Pipe-Buffer hängen kann.
    t = threading.Thread(target=_pump_logs, args=(up_proc,), daemon=True)
    t.start()

    # Handles für späteres Stoppen merken
    _BACKEND["up_proc"] = up_proc
    _BACKEND["compose_dir"] = compose_dir

    print("[BOOT] Backend bereit – starte GUI …", flush=True)


def stop_backend(down_with_volumes: bool = False):
    """
    Stoppt die via 'starte_backend()' gestartete Compose-Session sauber:
      - 'docker compose down' (optional mit -v)
      - beendet anschließend den 'up'-Prozess, falls er noch läuft
    """
    import subprocess, time

    up_proc = _BACKEND.get("up_proc")
    compose_dir = _BACKEND.get("compose_dir")
    if compose_dir is None:
        return  # nichts zu tun

    # Compose down (räumt Container sauber auf; 'up_proc' endet danach i. d. R. von selbst)
    down_cmd = ["docker", "compose", "down"] + (["-v"] if down_with_volumes else [])
    print(f"[STOP] $ {' '.join(down_cmd)}  (cwd={compose_dir})", flush=True)
    try:
        subprocess.run(down_cmd, cwd=str(compose_dir))
    except Exception as e:
        print(f"[STOP] Warnung: compose down fehlgeschlagen: {e}", flush=True)

    # up-Prozess ggf. noch beenden
    if up_proc and up_proc.poll() is None:
        try:
            up_proc.terminate()
            up_proc.wait(timeout=3)
        except Exception:
            try:
                up_proc.kill()
            except Exception:
                pass

    # Handles leeren
    _BACKEND["up_proc"] = None
    _BACKEND["compose_dir"] = None
