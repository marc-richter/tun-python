import subprocess
import platform
import os

def is_docker_running() -> bool:
    """Prüfen, ob Docker Daemon läuft."""
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def start_docker():
    """Docker starten – abhängig vom Betriebssystem."""
    system = platform.system()

    if system == "Linux":
        try:
            subprocess.run(["systemctl", "start", "docker"], check=True)
            print("Docker wurde auf Linux gestartet.")
        except Exception as e:
            print(f"Konnte Docker auf Linux nicht starten: {e}")

    elif system == "Darwin":  # macOS
        try:
            subprocess.Popen(["open", "-a", "Docker"])
            print("Docker Desktop auf macOS gestartet.")
        except Exception as e:
            print(f"Konnte Docker Desktop auf macOS nicht starten: {e}")

    elif system == "Windows":
        docker_path = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if os.path.exists(docker_path):
            try:
                subprocess.Popen([docker_path])
                print("Docker Desktop auf Windows gestartet.")
            except Exception as e:
                print(f"Konnte Docker Desktop auf Windows nicht starten: {e}")
        else:
            print("Docker Desktop nicht im Standardpfad gefunden.")

    else:
        print(f"Unbekanntes Betriebssystem: {system}")

def ensure_docker_running():
    if is_docker_running():
        print("Docker läuft bereits.")
        return 1
    else:
        print("Docker läuft NICHT. Starte jetzt...")
        start_docker()
        return 0

if __name__ == "__main__":
    ensure_docker_running()
