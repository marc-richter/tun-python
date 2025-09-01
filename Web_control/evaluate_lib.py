import datetime
import json

import matplotlib.pyplot as plt
import numpy as np


def ping_cdf_from_file(filename, timestamp, plot=True):
    """
    Liest eine Ping-JSON-Datei ein, extrahiert die Zeiten und erstellt eine CDF.

    Args:
        filename (str): Pfad zur Ping-JSON-Datei
        plot (bool): Wenn True, wird die CDF geplottet.

    Returns:
        file_name: Dateiname der Grafik
    """

    #Dateiname evaluieren
    file_name = f"{timestamp}-cdf.svg"
    savefile =  f"../logs/evaluated_data/{file_name}"


    # Datei laden
    with open(filename, "r") as f:
        data = json.load(f)

    # Zeitwerte extrahieren
    time_ms = [reply["time_ms"] for reply in data["replies"] if "time_ms" in reply]

    # Sortieren
    sorted_times = np.sort(time_ms)

    # CDF berechnen
    cdf_values = np.arange(1, len(sorted_times) + 1) / len(sorted_times)

    # Plot
    plt.figure()
    plt.step(sorted_times, cdf_values, where='post')
    plt.xlabel("Ping-Zeit (ms)")
    plt.ylabel("CDF")
    plt.title(f"CDF der Ping-Zeiten für {data['target']['hostname']}")
    plt.grid(True)

    # Abspeichern, falls gewünscht
    if savefile:
        plt.savefig(savefile, dpi=300, bbox_inches="tight")

    if plot:
        plt.show()
    else:
        plt.close()

    #return sorted_times, cdf_values
    return file_name


def ping_time_distribution(filename, timestamp, bins=10, plot=True):
    """
        Liest eine Ping-JSON-Datei ein und stellt die Verteilung der Ping-Zeiten dar.

        Args:
            filename (str): Pfad zur Ping-JSON-Datei.
            bins (int): Anzahl der Bins für das Histogramm.
            plot (bool): Wenn True, wird der Plot angezeigt.
            savefile (str): Dateiname zum Abspeichern (z.B. 'distribution.png').

        Returns:
            file_name: Dateiname der Grafik
        """
    # Dateiname evaluieren
    file_name = f"{timestamp}-hist.svg"
    savefile = f"../logs/evaluated_data/{file_name}"

    # Datei laden
    with open(filename, "r") as f:
        data = json.load(f)

    # Zeitwerte extrahieren
    time_ms = np.array([reply["time_ms"] for reply in data["replies"] if "time_ms" in reply])

    # Plot
    plt.figure()
    plt.hist(time_ms, bins=bins, density=True, alpha=0.6, color="steelblue", edgecolor="black")

    # Optionale Dichtekurve (nur wenn genug Werte vorhanden sind)
    if len(time_ms) > 1:
        from scipy.stats import gaussian_kde
        kde = gaussian_kde(time_ms)
        x_vals = np.linspace(time_ms.min(), time_ms.max(), 200)
        plt.plot(x_vals, kde(x_vals), color="red", lw=2, label="Dichte")
        plt.legend()

    plt.xlabel("Ping-Zeit (ms)")
    plt.ylabel("Relative Häufigkeit")
    plt.title(f"Verteilung der Ping-Zeiten für {data['target']['hostname']}")
    plt.grid(True)

    # Abspeichern, falls gewünscht
    if savefile:
        plt.savefig(savefile, dpi=300, bbox_inches="tight")

    if plot:
        plt.show()
    else:
        plt.close()

    return file_name


def get_timestamp():
    return datetime.datetime.now().strftime("%y-%m-%d_%H-%M")

def main(filename):
    # Timestamp wird als Benennungsgrundlage für den Dateinamen verwendet
    timestamp = get_timestamp()

    # Return Werte sind die Datei Namen
    ping_cdf_from_file(filename, timestamp)
    ping_time_distribution(filename, timestamp)


if __name__ == "__main__":
    main(filename="./../logs/container_a/ping_2025-08-27_16-54-08.json")