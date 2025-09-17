# services/ingestgw/normalize.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    out = dict(rec)

    # ts → ISO8601 (jeśli brak albo puste → wstaw teraz)
    ts = out.get("ts")
    if isinstance(ts, str) and ts.strip():
        out["_missing_ts"] = False
    else:
        out["_missing_ts"] = True
        out["ts"] = datetime.now(UTC).isoformat()

    # level → uppercase; nienapisowe traktujemy jako brak
    lvl = out.get("level")
    if isinstance(lvl, str) and lvl.strip():
        out["_missing_level"] = False
        out["level"] = lvl.strip().upper()
    else:
        out["_missing_level"] = True
        out["level"] = "INFO"

    # msg → string (zachowawczo zrzutuj, jeśli to np. dict/list/bool/int)
    msg = out.get("msg")
    if msg is None:
        out["msg"] = ""
    elif isinstance(msg, str):
        # pozostaw jak jest
        pass
    else:
        out["msg"] = str(msg)

    return out
