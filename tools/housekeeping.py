# tools/housekeeping.py
import os
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # .../logops
load_dotenv(ROOT / ".env", override=True)
cfg = dotenv_values(ROOT / ".env")


def getenv(name: str, default=None):
    """Prefer os.environ, then .env dict, finally default."""
    return os.getenv(name) or cfg.get(name, default)


# === Configuration ===
SINK_DIR = Path(getenv("LOGOPS_SINK_DIR", "./data/ingest") or "./data/ingest")
RETENTION_DAYS = int(getenv("LOGOPS_RETENTION_DAYS", "7") or "7")

# delete | zip
ARCHIVE_MODE = (getenv("LOGOPS_ARCHIVE_MODE", "delete") or "delete").lower()

ARCHIVE_DIR = ROOT / "data" / "archive"
if ARCHIVE_MODE == "zip":
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def parse_day(name: str):
    """Return datetime(UTC) parsed from YYYYMMDD filename stem or None."""
    try:
        return datetime.strptime(Path(name).stem, "%Y%m%d").replace(tzinfo=UTC)
    except Exception:
        return None


def main():
    """Single housekeeping pass: remove/archive expired NDJSON day files."""
    if not SINK_DIR.exists():
        print(f"[housekeep] {SINK_DIR} does not exist")
        return

    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)

    for p in SINK_DIR.glob("*.ndjson"):
        day = parse_day(p.name)
        if not day:
            continue
        if day < cutoff:
            if ARCHIVE_MODE == "zip":
                zip_path = ARCHIVE_DIR / (p.stem + ".zip")
                with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(p, arcname=p.name)
                p.unlink(missing_ok=True)
                print(f"[housekeep] archived {p.name} -> {zip_path.name}")
            else:  # delete
                p.unlink(missing_ok=True)
                print(f"[housekeep] deleted {p.name}")


# === Bridge for gateway ===
def run_once():
    """Uruchom housekeeping jednokrotnie (do użycia z gatewayem)."""
    main()


if __name__ == "__main__":
    main()
