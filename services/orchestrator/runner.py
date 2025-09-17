from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse  # <-- NEW

from .metrics import ORCH_EMITTED_TOTAL, ORCH_ERRORS_TOTAL, ORCH_RUNNING
from .models import ScenarioInfo, StartRequest

ROOT = Path(__file__).resolve().parents[2]  # repo root (../.. from services/orchestrator)
SCEN_DIR = ROOT / "scenarios"
DATA_DIR = ROOT / "data" / "orch"
LOG_DIR = DATA_DIR / "scenarios"
TMP_SCEN_DIR = DATA_DIR / "tmp_scenarios"
RUNNER = ROOT / "tools" / "run_scenario.py"

for d in (LOG_DIR, TMP_SCEN_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _with_sc(url: str, scenario_id: str) -> str:
    """Dopnij ?sc=<scenario_id> do URL-a (bez zmiany payloadu)."""
    if not url:
        return url
    u = urlparse(url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q["sc"] = scenario_id
    return urlunparse(u._replace(query=urlencode(q)))


class ScenarioProcess:
    __slots__ = (
        "scenario_id",
        "name",
        "proc",
        "status",
        "started_at",
        "updated_at",
        "log_file",
        "scenario_path",
        "dry_run",
        "debug",
        "seed",
        "strict",
        "step_timeout_sec",
        "_watch_task",
        "_tail_task",
        "_stop_requested",
    )

    def __init__(
        self,
        scenario_id: str,
        name: str,
        log_file: Path,
        scenario_path: Path,
        dry_run: bool,
        debug: bool,
        seed: int | None,
        strict: bool,
        step_timeout_sec: float,
    ):
        self.scenario_id = scenario_id
        self.name = name
        self.proc: asyncio.subprocess.Process | None = None
        self.status = "created"
        self.started_at = time.time()
        self.updated_at = self.started_at
        self.log_file = str(log_file)
        self.scenario_path = str(scenario_path)
        self.dry_run = dry_run
        self.debug = debug
        self.seed = seed
        self.strict = strict
        self.step_timeout_sec = step_timeout_sec
        self._watch_task: asyncio.Task | None = None
        self._tail_task: asyncio.Task | None = None
        self._stop_requested = False


class Orchestrator:
    def __init__(self):
        self._by_id: dict[str, ScenarioProcess] = {}
        self._lock = asyncio.Lock()

    def _gen_id(self) -> str:
        # krótki, czytelny identyfikator
        return "sc-" + uuid.uuid4().hex[:12]

    def _resolve_scenario_path(self, req: StartRequest, sid: str) -> Path:
        if req.yaml_path:
            p = (
                (ROOT / req.yaml_path).resolve()
                if not Path(req.yaml_path).is_absolute()
                else Path(req.yaml_path)
            )
            if not p.exists():
                raise FileNotFoundError(f"scenario file not found: {p}")
            return p

        if req.name:
            for ext in (".yaml", ".yml"):
                cand = (SCEN_DIR / f"{req.name}{ext}").resolve()
                if cand.exists():
                    return cand
            raise FileNotFoundError(f"scenario '{req.name}' not found in {SCEN_DIR}")

        if req.inline:
            out = TMP_SCEN_DIR / f"{sid}.yaml"
            import yaml  # FastAPI/uvicorn środowisko i tak ma pyyaml w projekcie

            with out.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(req.inline, fh, sort_keys=False, allow_unicode=True)
            return out

        raise ValueError("no scenario provided (name|yaml_path|inline)")

    async def start(self, req: StartRequest) -> ScenarioProcess:
        sid = self._gen_id()
        scen_path = self._resolve_scenario_path(req, sid)
        name = (req.name or req.inline.get("name") if req.inline else None) or scen_path.stem

        log_file = LOG_DIR / f"{sid}.jsonl"

        sp = ScenarioProcess(
            scenario_id=sid,
            name=name,
            log_file=log_file,
            scenario_path=scen_path,
            dry_run=req.dry_run,
            debug=req.debug,
            seed=req.seed,
            strict=req.strict,
            step_timeout_sec=req.step_timeout_sec,
        )

        # uruchom runner
        py = req.py or sys.executable
        cmd = [
            py,
            str(RUNNER),
            "-s",
            str(scen_path),
            "--log-file",
            str(log_file),
            "--step-timeout",
            str(req.step_timeout_sec),
        ]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.debug:
            cmd.append("--debug")
        if req.strict:
            cmd.append("--strict")
        if req.seed is not None:
            cmd += ["--seed", str(req.seed)]

        env = os.environ.copy()
        # Najważniejsze: korelacja po scenario_id
        env["LOGOPS_SCENARIO"] = sid

        # (opcjonalne) nadpisania z requestu
        for k, v in (req.env_overrides or {}).items():
            env[str(k)] = str(v)

        # DOPNIJ ?sc=<sid> do ENTRYPOINT_URL / CORE_URL jeżeli są ustawione (bez zmiany payloadu)
        ep = env.get("ENTRYPOINT_URL")
        if ep:
            env["ENTRYPOINT_URL"] = _with_sc(ep, sid)
        cu = env.get("CORE_URL")
        if cu:
            env["CORE_URL"] = _with_sc(cu, sid)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        sp.proc = proc
        sp.status = "running"
        sp.started_at = time.time()
        sp.updated_at = sp.started_at

        # metryka "running"
        try:
            ORCH_RUNNING.labels(scenario_id=sid, name=name).set(1)
        except Exception:
            pass

        # watcher: tail JSONL (ticki/statystyki)
        sp._tail_task = asyncio.create_task(self._tail_jsonl(sp))
        # watcher: czytaj stdout/stderr żeby nie blokować buforów
        sp._watch_task = asyncio.create_task(self._pump_stdio(sp))

        async with self._lock:
            self._by_id[sid] = sp
        return sp

    async def stop(self, scenario_id: str) -> bool:
        async with self._lock:
            sp = self._by_id.get(scenario_id)
        if not sp or not sp.proc:
            return False
        if sp.status not in ("running", "created"):
            return True

        sp._stop_requested = True
        try:
            sp.proc.send_signal(signal.SIGINT)  # run_scenario.py ma handler SIGINT → graceful stop
        except ProcessLookupError:
            pass

        try:
            await asyncio.wait_for(sp.proc.wait(), timeout=10.0)
        except TimeoutError:
            # ostatecznie SIGKILL
            try:
                sp.proc.kill()
            except ProcessLookupError:
                pass

        await self._finalize(sp)
        return True

    async def list(self) -> dict[str, ScenarioProcess]:
        async with self._lock:
            return dict(self._by_id)

    async def _finalize(self, sp: ScenarioProcess) -> None:
        # Ustaw status + metryki
        code = None
        try:
            if sp.proc is not None:
                code = sp.proc.returncode
        except Exception:
            pass
        if sp._stop_requested:
            sp.status = "stopped"
        elif code is not None and code != 0:
            sp.status = "error"
        else:
            sp.status = "finished"
        sp.updated_at = time.time()

        try:
            ORCH_RUNNING.labels(scenario_id=sp.scenario_id, name=sp.name).set(0)
        except Exception:
            pass

    async def _pump_stdio(self, sp: ScenarioProcess) -> None:
        assert sp.proc is not None

        async def _drain(stream, tag: str):
            if not stream:
                return
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    txt = line.decode(errors="replace").strip()
                    if "[error]" in txt.lower():
                        try:
                            ORCH_ERRORS_TOTAL.labels(sp.scenario_id, "runner_error_line").inc()
                        except Exception:
                            pass
            except Exception:
                pass

        await asyncio.gather(_drain(sp.proc.stdout, "stdout"), _drain(sp.proc.stderr, "stderr"))
        # Proces się zakończył → finalize
        await self._finalize(sp)

    async def _tail_jsonl(self, sp: ScenarioProcess) -> None:
        """Tailing pliku JSONL tworzonego przez tools/run_scenario.py (ticki + end)."""
        path = Path(sp.log_file)
        # czekamy aż plik powstanie
        for _ in range(100):
            if path.exists():
                break
            await asyncio.sleep(0.05)

        try:
            with path.open("r", encoding="utf-8") as fh:
                fh.seek(0)
                while True:
                    where = fh.tell()
                    line = fh.readline()
                    if not line:
                        await asyncio.sleep(0.25)
                        fh.seek(where)
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    typ = rec.get("type")

                    if typ == "tick":
                        n = int(rec.get("n") or 0)
                        emitter = str(rec.get("emitter") or "unknown")
                        if n > 0:
                            try:
                                ORCH_EMITTED_TOTAL.labels(sp.scenario_id, emitter).inc(n)
                            except Exception:
                                pass
                    elif typ == "error":
                        reason = (rec.get("reason") or "step_rc") if "reason" in rec else "step_rc"
                        try:
                            ORCH_ERRORS_TOTAL.labels(sp.scenario_id, str(reason)).inc()
                        except Exception:
                            pass
                    elif typ in ("scenario.start", "scenario.end"):
                        pass
        except Exception:
            try:
                ORCH_ERRORS_TOTAL.labels(sp.scenario_id, "tail_jsonl").inc()
            except Exception:
                pass


# singleton
ORCH = Orchestrator()


def to_info(sp: ScenarioProcess) -> ScenarioInfo:
    pid = sp.proc.pid if sp.proc and sp.proc.returncode is None else None
    return ScenarioInfo(
        scenario_id=sp.scenario_id,
        name=sp.name,
        status=sp.status,
        pid=pid,
        started_at=sp.started_at,
        updated_at=sp.updated_at,
        log_file=sp.log_file,
        scenario_path=sp.scenario_path,
        dry_run=sp.dry_run,
        debug=sp.debug,
        seed=sp.seed,
        strict=sp.strict,
        step_timeout_sec=sp.step_timeout_sec,
    )
