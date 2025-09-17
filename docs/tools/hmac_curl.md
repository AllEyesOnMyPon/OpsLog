# `tools/hmac_curl.sh` — wrapper `curl` z podpisem HMAC dla AuthGW

Skrypt Bash, który:
- liczy **HMAC** (korzystając z `tools/sign_hmac.py`),
- dokłada wymagane nagłówki (`X-Api-Key`, `X-Timestamp`, `X-Content-SHA256`, `X-Signature`, opcjonalnie `X-Nonce`),
- wysyła żądanie `curl` do **Auth Gateway** (`/ingest` domyślnie),
- daje pełną kontrolę: metoda, URL, body (inline/plik), własne nagłówki, verbose, debug.

> Używa **tej samej kanonikalizacji** co serwer (`HmacAuthMiddleware`). Dzięki temu to, co podpisujesz, przejdzie walidację po stronie AuthGW.

**Plik:** `tools/hmac_curl.sh`
**Wymagania:** `bash`, `python3` (do uruchomienia `tools/sign_hmac.py`)
**Domyślne poświadczenia (ENV):** `LOGOPS_API_KEY=demo-pub-1`, `LOGOPS_SECRET=demo-priv-1`
**Domyślny URL:** `$ENTRYPOINT_URL` lub `http://127.0.0.1:8081/ingest`

---

## Szybki start

**Inline JSON + nonce (zalecane):**
```bash
tools/hmac_curl.sh --nonce -d '{"msg":"hello"}'
```

**Body z pliku (np. CSV):**
```bash
echo 'ts,level,msg' > body.csv
echo '2025-01-01T00:00:00Z,INFO,"hi!"' >> body.csv
tools/hmac_curl.sh --nonce -f body.csv -H 'Content-Type: text/csv'
```

**GET bez body (np. endpoint debugowy):**
```bash
tools/hmac_curl.sh -X GET -u 'http://127.0.0.1:8081/_debug/hdrs' --nonce
```

**Tylko wypisz nagłówki (`-H "K: V" -H "K: V" ...`) i wyjdź:**
```bash
tools/hmac_curl.sh --nonce -d '[]' --echo-headers
```

---

## Składnia i opcje

```
tools/hmac_curl.sh [opcje] [-- ...dodatkowe-argumenty-dla-curl]

-u, --url URL            Docelowy URL (dom: $ENTRYPOINT_URL lub http://127.0.0.1:8081/ingest)
-X, --method M           Metoda HTTP (dom: POST)
-k, --key KEY            X-Api-Key (dom: $LOGOPS_API_KEY lub demo-pub-1)
-s, --secret S           Sekret HMAC (dom: $LOGOPS_SECRET lub demo-priv-1)
-d, --data STR           Body inline (string)
-f, --file PATH          Body z pliku (wysyłane jako --data-binary @PATH)
-H "Header: V"           Dodatkowy nagłówek (opcja powtarzalna)
    --nonce              Dodaj X-Nonce (domyślnie WŁĄCZONE)
    --no-nonce           Nie dodawaj X-Nonce
    --ts ISO             Wymuś timestamp (ISO Z)
    --ts-offset SPEC     Przesuń timestamp (np. +30s, -2m, +1h)
    --echo-headers       Zwróć tylko nagłówki jako: -H "K: V" -H "K: V"... i zakończ
-v, --verbose            Włącz verbose curl
-h, --help               Pomoc
--                       Oddzielacz — wszystko po nim trafia **bez zmian** do curl
```

**Zachowanie domyślne `Content-Type`:**
- Skrypt **doda** `Content-Type: application/json` **tylko** jeśli:
  1) metoda ≠ `GET`, **i**
  2) podano body (`-d` lub `-f`), **i**
  3) **nie** przesłoniłeś `Content-Type` własnym `-H`.
- Dla CSV/tekst ustaw `-H 'Content-Type: text/csv'` lub `-H 'Content-Type: text/plain'`.

---

## Zmienne środowiskowe

| Zmienna           | Domyślnie                              | Opis |
|---|---|---|
| `ENTRYPOINT_URL`  | `http://127.0.0.1:8081/ingest`         | URL docelowy, jeśli nie podasz `-u/--url` |
| `LOGOPS_API_KEY`  | `demo-pub-1`                           | Publiczny klucz klienta (`X-Api-Key`) |
| `LOGOPS_SECRET`   | `demo-priv-1`                          | Sekret HMAC (do podpisu) |

> Sekrety trzymaj poza Gitem (np. `.env.local`, menedżer sekretów, eksport sesyjny).

---

## Jak to działa (pod maską)

1. Skrypt buduje parametry dla `tools/sign_hmac.py` (metoda, URL, body, opcjonalnie `--nonce`, `--ts`, `--ts-offset`).
2. Uruchamia signer w Pythonie, który wypluwa **nagłówki HMAC** w formacie `"K: V"` (jeden na linię) z **tą samą kanonikalizacją**, co serwerowy middleware.
3. Konwertuje je na argumenty `curl` (`-H "K: V"`), dołącza Twoje nagłówki i wysyła:
   ```bash
   curl -sS -X "$METHOD" "$URL" \
     -H "X-Api-Key: ..." -H "X-Timestamp: ..." -H "X-Content-SHA256: ..." -H "X-Signature: ..." [-H "X-Nonce: ..."] \
     [Twoje -H ...] [--data-binary @PLIK | --data '...']
   ```
4. `--echo-headers` pozwala użyć skryptu jedynie do **wygenerowania nagłówków**, które wkleisz do własnego `curl`/narzędzia.

---

## Przykłady praktyczne

**1) JSON batch:**
```bash
tools/hmac_curl.sh --nonce -d '[{"msg":"hi","level":"info"}]'
```

**2) CSV:**
```bash
tools/hmac_curl.sh --nonce -f /tmp/events.csv -H 'Content-Type: text/csv'
```

**3) Syslog-like (text/plain):**
```bash
printf '2025-01-01 12:00:00 INFO host app[123]: hello\n' > /tmp/line.txt
tools/hmac_curl.sh --nonce -f /tmp/line.txt -H 'Content-Type: text/plain'
```

**4) Własne timeouty/flag w `curl`:**
```bash
tools/hmac_curl.sh --nonce -d '[]' -- --max-time 5 --http1.1 -i
```

**5) Tylko nagłówki HMAC (do debugowania):**
```bash
tools/hmac_curl.sh --nonce -d '[]' --echo-headers
# => -H "X-Api-Key: ..." -H "X-Timestamp: ..." -H "X-Content-SHA256: ..." -H "X-Signature: ..." -H "X-Nonce: ..."
```

**6) Test odchyłki czasu (spodziewane 401 skew):**
```bash
tools/hmac_curl.sh --nonce --ts-offset -3600 -d '{"msg":"old"}' -- -i -s -o /dev/null -w "code:%{http_code}\n" -D -
```

---

## Najczęstsze problemy i wskazówki

- **401 body hash mismatch** — podpis liczony jest po **dokładnych bajtach**. Używaj `--data-binary @PLIK` (skrypt zrobi to automatycznie dla `-f`). Przy `-d` skrypt sam przekaże tekst bez modyfikacji.
- **401 bad signature** — niespójne `METHOD`/`URL`/`body`/`X-Timestamp` między podpisem a wysyłką. Nie zmieniaj nic „po drodze”.
- **401 timestamp skew** — zegary się rozjechały; użyj `--ts` albo `--ts-offset`, lub zsynchronizuj czas.
- **401 replay detected** — ponownie użyty `X-Nonce` przy włączonym anty-replay (Redis). Pozostaw `--nonce` (generuje nowy), lub wyłącz w serwerze `require_nonce=false`.
- **Content-Type** — pamiętaj ustawić `text/csv` / `text/plain` dla CSV/syslog; domyślny `application/json` jest dodawany tylko przy body i braku Twojego `-H`.

---

## Integracja z Makefile

W repo znajdują się cele korzystające z tego skryptu (np. szybkie testy AuthGW/backpressure).
Możesz też osadzić `--echo-headers` w swoich celach, by generować nagłówki offline.

---

## Zobacz też

- `tools/sign_hmac.py` — silnik podpisywania (kanonikalizacja zgodna z serwerem)
- `services/authgw/hmac_mw.py` — walidacja HMAC po stronie serwera
- `services/authgw/app.py` & `downstream.py` — forwarding z retry i circuit breakerem
- `tools/verify_hmac_against_signer.py` — weryfikacja nagłówków/podpisu z przygotowanego żądania
