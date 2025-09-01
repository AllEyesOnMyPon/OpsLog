# Konfiguracja środowiska LogOps (`.env`)

Plik `.env` definiuje zachowanie serwisów **Ingest Gateway**, housekeeping oraz integrację z Alertmanagerem/Slackiem.  
W repozytorium znajdziesz szablon: `.env.example`.

---

## Encryption settings

| Zmienna                | Typ       | Domyślna | Opis |
|-------------------------|----------|----------|------|
| `LOGOPS_SECRET_KEY`     | string   | brak     | Klucz używany do szyfrowania PII (Fernet). Musi być poprawnym 32-bajtowym ciągiem Base64. |
| `LOGOPS_ENCRYPT_PII`    | bool     | `false`  | Włącza szyfrowanie pól wrażliwych. |
| `LOGOPS_ENCRYPT_FIELDS` | csv list | `user_email,client_ip` | Lista dodatkowych pól do szyfrowania. |

---

## Debugging & sampling

| Zmienna                   | Typ   | Domyślna | Opis |
|----------------------------|------|----------|------|
| `LOGOPS_DEBUG_SAMPLE`      | bool | `false`  | Jeśli `true`, gateway w odpowiedzi `/v1/logs` zwraca próbkę znormalizowanych rekordów. |
| `LOGOPS_DEBUG_SAMPLE_SIZE` | int  | `2`      | Maksymalna liczba rekordów w próbce debugowej. |

---

## File sink (persistent storage)

| Zmienna           | Typ   | Domyślna        | Opis |
|--------------------|------|-----------------|------|
| `LOGOPS_SINK_FILE` | bool | `false`         | Jeśli `true`, zapisuje przyjęte rekordy do pliku NDJSON. |
| `LOGOPS_SINK_DIR`  | path | `./data/ingest` | Katalog, gdzie zapisywane są pliki NDJSON (jeden plik na dzień). |

---

## Housekeeping (file lifecycle)

| Zmienna                | Typ   | Domyślna | Opis |
|-------------------------|------|----------|------|
| `LOGOPS_RETENTION_DAYS` | int  | `7`      | Liczba dni trzymania plików w `LOGOPS_SINK_DIR`. |
| `LOGOPS_ARCHIVE_MODE`   | enum | `delete` | Co robić z plikami po terminie: <br>`delete` – usuwa, <br>`zip` – archiwizuje do ZIP. |

---

## Housekeeping autorun (gateway lifespan)

| Zmienna                         | Typ   | Domyślna | Opis |
|---------------------------------|------|----------|------|
| `LOGOPS_HOUSEKEEP_AUTORUN`      | bool | `false`  | Jeśli `true`, housekeeping startuje automatycznie razem z gateway. |
| `LOGOPS_HOUSEKEEP_INTERVAL_SEC` | int  | `0`      | Interwał (w sekundach) między kolejnymi uruchomieniami housekeeping. Jeśli `0` → tylko jednorazowe uruchomienie na starcie. |

---

## Alertmanager / Slack

| Zmienna                          | Typ     | Domyślna | Opis |
|----------------------------------|--------|----------|------|
| `ALERTMANAGER_SLACK_WEBHOOK`     | string | brak     | Webhook Slack do Alertmanagera (ogólny). |
| `ALERTMANAGER_SLACK_WEBHOOK_LOGOPS` | string | brak  | Webhook Slack specyficzny dla alertów LogOps (może być taki sam jak wyżej). |

---

## Przykład (`.env`)

```env
LOGOPS_SECRET_KEY=H0JFlLBAZirMvzzQD-lQziWhRGesRXWQMK1nA1u5b5k=
LOGOPS_ENCRYPT_PII=true
LOGOPS_ENCRYPT_FIELDS=user_email,client_ip

LOGOPS_DEBUG_SAMPLE=true
LOGOPS_DEBUG_SAMPLE_SIZE=3

LOGOPS_SINK_FILE=true
LOGOPS_SINK_DIR=./data/ingest

LOGOPS_RETENTION_DAYS=2
LOGOPS_ARCHIVE_MODE=delete

LOGOPS_HOUSEKEEP_AUTORUN=true
LOGOPS_HOUSEKEEP_INTERVAL_SEC=0

ALERTMANAGER_SLACK_WEBHOOK=https://hooks.slack.com/services/XXX/YYY/ZZZ
ALERTMANAGER_SLACK_WEBHOOK_LOGOPS=https://hooks.slack.com/services/XXX/YYY/ZZZ
```
