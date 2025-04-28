# Channel Processor

Dieses Projekt implementiert einen RabbitMQ-Channel-Processor, der Netzwerkpakete verzögern oder verwerfen kann, basierend auf einer konfigurierten mathematischen Verteilung. Es hört auf zwei RabbitMQ-Queues (`request_queue` und `reply_queue`) und leitet die Pakete nach Verarbeitung an zwei andere Queues (`request_queue_after_channel` und `reply_queue_after_channel`) weiter.

---

## **Features**
- Verzögerung von Paketen basierend auf konfigurierbaren Verteilungen (z. B. Exponential, Normal, Uniform).
- Zufälliges Verwerfen von Paketen basierend auf einer Drop-Wahrscheinlichkeit.
- Konfigurierbare Parameter wie minimale/maximale Verzögerung, Jitter und Drop-Wahrscheinlichkeit.
- Unterstützung für Exponential Backoff mit Jitter bei Fehlern.
- Detailliertes Logging aller Operationen.
- Konfiguration über eine YAML-Datei (`channel.yml`).

---

## **Dateistruktur**
├── common.py # Gemeinsame Funktionen (RabbitMQ-Verbindung, TUN-Gerät)
├── channel.py # Hauptskript für den Channel Processor
├── channel.yml # Konfigurationsdatei
└── README.md # Dokumentation


---

## **Funktionsweise**

### Hauptskript (`channel.py`)
Das Skript führt folgende Schritte aus:
1. **RabbitMQ-Verbindung**:
   - Stellt eine Verbindung zu RabbitMQ her und deklariert die benötigten Queues.
   - Die Queues sind:
     - `network_request`: Eingangsqueue für Anfragenpakete.
     - `network_reply`: Eingangsqueue für Antwortpakete.
     - `network_request_after_channel`: Ausgangsqueue für verarbeitete Anfragenpakete.
     - `network_reply_after_channel`: Ausgangsqueue für verarbeitete Antwortpakete.

2. **Verarbeitung von Paketen**:
   - Pakete werden entweder verzögert oder verworfen, basierend auf den Parametern in `channel.yml`.
   - Die Verzögerung wird durch eine mathematische Verteilung berechnet (Exponential, Normal oder Uniform).
   - Jitter wird hinzugefügt, um die Verzögerungen realistischer zu gestalten.

3. **Retry-Mechanismus**:
   - Wenn ein Fehler auftritt (z. B. beim Weiterleiten eines Pakets), wird ein Retry mit Exponential Backoff durchgeführt.
   - Die maximale Anzahl von Retries und die Basisverzögerung können konfiguriert werden.

4. **Logging**:
   - Das Skript protokolliert alle wichtigen Ereignisse wie Paketverzögerungen, verworfene Pakete und Fehler.

---

## **Parameter-Erklärung**

### Channel-Parameter (`request_channel` und `reply_channel`)
| Parameter           | Beschreibung                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| `min_delay`         | Minimale Verzögerung in Millisekunden                                       |
| `max_delay`         | Maximale Verzögerung in Millisekunden                                       |
| `jitter`            | Zufällige zusätzliche Verzögerung in Millisekunden                         |
| `drop_probability`  | Wahrscheinlichkeit, dass ein Paket verworfen wird (Wert zwischen 0 und 1) |
| `distribution.type` | Typ der mathematischen Verteilung (exponential, normal, uniform)           |
| `distribution.parameters` | Parameter der Verteilung (z. B. Lambda für Exponentialverteilung) |

### Retry-Parameter (`retry`)
| Parameter       | Beschreibung                                                                 |
|-----------------|-----------------------------------------------------------------------------|
| `base_delay`    | Basisverzögerung für Retries in Millisekunden                               |
| `jitter`        | Zufällige zusätzliche Verzögerung bei Retries                               |
| `max_retries`   | Maximale Anzahl von Retries pro Paket                                       |

---

## **Verwendung**

### Starten des Channel Processors
```bash
python3 channel.py
```

## **Mathematische Verteilungen**

### Unterstützte Typen:
1. **Exponentialverteilung**:
    ```python
    delay = np.random.exponential(lambda)
    ```
    Beispielparameter: `{ "lambda": 0.1 }`
2. **Normalverteilung**:
    ```python
    delay = np.random.normal(mu, sigma)
    ```
    Beispielparameter: `{ "mu": 0, "sigma": 1 }`
3. **Uniformverteilung**:
    ```python
    delay = np.random.uniform(low, high)
    ```
    Beispielparameter: `{ "low": 0, "high": 1 }`


---

## **Erweiterungsmöglichkeiten**
1. Unterstützung weiterer mathematischer Verteilungen wie Gamma oder Poisson.
2. Dynamische Konfiguration ohne Neustart des Skripts.
3. Integration mit Monitoring-Systemen wie Prometheus.
4. Circuit Breaker Pattern zur Fehlerbehandlung.
5. Priorisierte Queues mit RabbitMQ.

---

## **Fehlerbehandlung**
Das Skript behandelt folgende Fehlerfälle:
1. **RabbitMQ-Verbindungsfehler**:
- Automatische Wiederherstellung der Verbindung durch Pika.
2. **Paketweiterleitungsfehler**:
- Retry mit Exponential Backoff und Jitter.
3. **Maximale Anzahl von Retries erreicht**:
- Protokollierung des Fehlers und Ignorieren des Pakets.

---

### Testfall mit Drop-Wahrscheinlichkeit:
Setzen Sie die Drop-Wahrscheinlichkeit auf einen hohen Wert (`drop_probability = 0.9`) und überprüfen Sie das Log.

---

