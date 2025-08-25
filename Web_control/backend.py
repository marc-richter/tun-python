#!/usr/bin/env python3

import subprocess
import datetime

'''
Backend zum IU mit folgenden Funktionalitäten:
    -  starten der gesamten Simulation
    -  Kommunikation über rabbit mq mit dem Web UI
    -  Einstellungen an Kanaleigenschaften vornehmen
    -  logs auswerten und graphisch visualisieren
'''








def start_simulation():
    # Zeitstempel-Logdatei
    timestamp = datetime.datetime.now().strftime("%y-%m-%d_%H-%M")
    logfile_name = f"{timestamp}.log"
    logfile_path = f"../logs/docker/{logfile_name}"

    # Simulationsumgebung starten
    with open(logfile_path, "a") as logfile:
        process = subprocess.Popen(
            "docker compose down -v && docker compose up --build",
            shell=True,     # Shell nötig für &&
            stdout=logfile, # Ausgabe ins Logfile
            stderr=logfile, # Ausgabe ins Logfile
            text=True
        )
#TODO: Simulation beenden

def main():
    #TODO: UI Starten
    #TODO: Kanaleigenschaften einstellen
    start_simulation()
    #TODO: Nach Ende der Simulation muss diese beendet werden
    #TODO: Logs auswerten und graphisch aufbereiten
    #TODO: Simulationsergebnisse online darstellen




if __name__ == "__main__":
    main()
