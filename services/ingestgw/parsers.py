# services/ingestgw/parsers.py
from __future__ import annotations

import csv
import io
import re
from typing import Any

_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARN|ERROR|TRACE|FATAL)\b", re.IGNORECASE)


def parse_syslog_line(line: str) -> dict[str, Any]:
    """
    Minimalny parser syslog-like:
    - msg = pełna linia,
    - level: wyciągnięty z tokena, jeśli występuje; inaczej INFO.
    """
    lvl = "INFO"
    m = _LEVEL_RE.search(line or "")
    if m:
        lvl = m.group(1).upper()
    return {"level": lvl, "msg": line}


def parse_csv_text_body(text: str) -> list[dict[str, Any]]:
    """
    CSV o strukturze (ts, level, msg), z opcjonalnym nagłówkiem.
    Obsługuje cudzysłowy i przecinki w polu msg (używa csv.reader).
    """
    out: list[dict[str, Any]] = []
    if not text:
        return out

    f = io.StringIO(text)
    reader = csv.reader(f)
    first_data_seen = False

    # dopuszczalne aliasy nagłówków
    def _is_header(row: list[str]) -> bool:
        r = [c.strip().lower() for c in row]
        if len(r) < 3:
            return False
        return (
            r[0] in ("ts", "timestamp")
            and r[1] in ("level", "lvl", "severity")
            and r[2] in ("msg", "message", "log", "text")
        )

    for row in reader:
        if not row or all((c or "").strip() == "" for c in row):
            continue
        # pierwszy niepusty wiersz: jeśli to nagłówek, pomijamy
        if not first_data_seen and _is_header(row):
            first_data_seen = True
            continue
        first_data_seen = True

        # mapowanie kolumn
        ts = row[0].strip() if len(row) > 0 else ""
        level = row[1].strip() if len(row) > 1 else ""
        # wiadomość może zawierać przecinki → łączymy resztę
        msg = ",".join(row[2:]).strip() if len(row) > 2 else ""

        out.append({"ts": ts, "level": level, "msg": msg})

    return out
