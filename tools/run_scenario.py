#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
import yaml
import shlex
import signal
import json
import re
import random
from pathlib import Path
from collections import defaultdict, Counter
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

# Domyślne emitery (kompatybilne ze starym YAMLem)
EMITTERS = {
    "emitter_csv":     "emitters/emitter_csv/emit_csv.py",
    "emitter_json":    "emitters/emitter_json/emit_json.py",
    "emitter_minimal": "emitters/emitter_minimal/emit_minimal.py",
    "emitter_noise":   "emitters/emitter_noise/emit_noise.py",
    "emitter_syslog":  "emitters/emitter_syslog/emit_syslog.py",
}

SC_STAT_RE = re.compile(r"^\s*SC_STAT\s+(?P<json>\{.*\})\s*$")

_STOP = False
def _on_sigint(sig, frame):
    global _STOP
    _STOP = True
    print("[scenario] SIGINT received, stopping gracefully after current tick...", flush=True)

signal.signal(signal.SIGINT, _on_sigint)

def _resolve_script(emitter_name: str, override_path: Optional[str]) -> Path:
    """
    Zwraca ścieżkę do skryptu emitera.
    - Jeśli w YAML emiter ma 'script', użyj jej (plugin).
    - W przeciwnym razie użyj mapy EMITTERS (wsteczna kompatybilność).
    """
    if override_path:
        p = (ROOT / override_path).resolve()
        if not p.exists():
            raise RuntimeError(f"Emitter script not found: {p}")
        return p
    rel = EMITTERS.get(emitter_name)
    if not rel:
        raise RuntimeError(f"Unknown emitter: {emitter_name} (and no 'script' provided)")
    p = (ROOT / rel).resolve()
    if not p.exists():
        raise RuntimeError(f"Emitter script not found: {p}")
    return p

def _build_cmd(py: str, script: Path, n: int, args: dict) -> List[str]:
    cmd = [py, str(script), "-n", str(n)]
    # ujednolicone, opcjonalne argumenty wspólne
    if "partial_ratio" in args:
        cmd += ["--partial-ratio", str(args["partial_ratio"])]
    if "chaos" in args:
        cmd += ["--chaos", str(args["chaos"])]
    if "seed" in args and args["seed"] is not None:
        cmd += ["--seed", str(args["seed"])]
    return cmd

def _run_subprocess(cmd: List[str], timeout: Optional[float], debug: bool) -> Tuple[int, str, str]:
    if debug:
        print(">>", " ".join(shlex.quote(c) for c in cmd), flush=True)
    try:
        out = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if out.stdout:
            sys.stdout.write(out.stdout)
            sys.stdout.flush()
        if out.stderr:
            sys.stderr.write(out.stderr)
            sys.stderr.flush()
        return out.returncode, (out.stdout or ""), (out.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"[warn] step timed out (>{timeout}s), continuing...", flush=True)
        return 124, "", ""
    except KeyboardInterrupt:
        return -2, "", ""

def _parse_sc_stat(stdout: str) -> dict:
    if not stdout:
        return {}
    last = {}
    for line in stdout.splitlines():
        m = SC_STAT_RE.match(line)
        if m:
            try:
                last = json.loads(m.group("json"))
            except json.JSONDecodeError:
                pass
    return last

def _now_epoch_iso() -> Tuple[float, str]:
    now = time.time()
    iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    return now, iso

def _effective_eps_with_meta(
    base_eps: float,
    t_rel: float,
    start_after: float,
    stop_after: Optional[float],
    ramp_up: float,
    ramp_down: float,
    jitter_pct: float,
) -> Tuple[float, bool, float]:
    """
    Wylicz efektywne EPS wg harmonogramu i zwróć:
      (eff_eps, in_window, jitter_scale)

    - cisza przed start_after
    - ramp_up do base_eps przez ramp_up sekund
    - plateau na base_eps
    - ramp_down do zera w ramp_down sekund przed stop_after (jeśli jest)
    - jitter_pct (0..1) losowo modyfikuje ±pct
    """
    in_window = (t_rel >= start_after) and (stop_after is None or t_rel < stop_after)
    if not in_window:
        return 0.0, False, 1.0

    t_from_start = t_rel - start_after

    # ramp-up
    if ramp_up > 0 and t_from_start < ramp_up:
        frac = max(0.0, min(1.0, t_from_start / ramp_up))
        eps = base_eps * frac
    else:
        eps = base_eps

    # ramp-down (jeśli zdefiniowany stop_after)
    if stop_after is not None and ramp_down > 0:
        t_to_stop = stop_after - t_rel
        if t_to_stop <= ramp_down:
            frac = max(0.0, min(1.0, t_to_stop / ramp_down))
            eps = eps * frac

    jitter_scale = 1.0
    if jitter_pct > 0:
        jitter_scale = 1.0 + random.uniform(-jitter_pct, jitter_pct)
        eps = max(0.0, eps * jitter_scale)

    return eps, True, jitter_scale

def _open_log(log_file: Optional[Path]):
    if not log_file:
        return None
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return log_file.open("a", encoding="utf-8")

def _log_jsonl(fh, obj: dict):
    if fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fh.flush()

def run_scenario(
    scn_path: Path,
    py: str,
    strict: bool,
    step_timeout: Optional[float],
    dry_run: bool,
    debug: bool,
    log_file: Optional[Path],
    seed: Optional[int],
):
    if seed is not None:
        random.seed(seed)

    with open(scn_path, "r", encoding="utf-8") as fh:
        scn = yaml.safe_load(fh)

    name = scn.get("name", scn_path.stem)
    duration = float(scn.get("duration_sec", 30))
    tick = float(scn.get("tick_sec", 1.0))
    emitters = scn.get("emitters", [])

    # Akumulatory
    sent_approx = Counter()             # ile "wysłano" (lub planowano – dry-run)
    levels_total = defaultdict(Counter) # per-emitter: Counter(level->count)
    errors_total = Counter()            # błędy procesów

    logfh = _open_log(log_file)
    now_epoch, now_iso = _now_epoch_iso()
    _log_jsonl(logfh, {
        "type": "scenario.start",
        "name": name,
        "duration_sec": duration,
        "tick_sec": tick,
        "dry_run": dry_run,
        "debug": debug,
        "seed": seed,
        "emitters": [e.get("name") for e in emitters],
        "ts": now_epoch,
        "ts_iso": now_iso,
        "scenario_path": str(scn_path),
        "py": py,
        "strict": strict,
        "step_timeout_sec": step_timeout,
    })

    print(f"[scenario] {name} | duration={duration:.0f}s tick={tick:.2f}s emitters={len(emitters)} dry_run={dry_run} debug={debug}")

    started = time.time()
    while (time.time() - started) < duration and not _STOP:
        loop_start = time.time()
        t_rel = loop_start - started

        for e in emitters:
            ename = e["name"]
            # parametry planowania
            base_eps = float(e.get("eps", 10.0))
            sched = e.get("schedule", {}) or {}
            start_after = float(sched.get("start_after_sec", 0.0))
            stop_after = sched.get("stop_after_sec")
            stop_after = float(stop_after) if stop_after is not None else None
            ramp_up = float(sched.get("ramp_up_sec", 0.0))
            ramp_down = float(sched.get("ramp_down_sec", 0.0))
            jitter_pct = float(sched.get("jitter_pct", 0.0))

            eff_eps, in_window, jitter_scale = _effective_eps_with_meta(
                base_eps,
                t_rel,
                start_after=start_after,
                stop_after=stop_after,
                ramp_up=ramp_up,
                ramp_down=ramp_down,
                jitter_pct=jitter_pct,
            )
            n = max(0, int(round(eff_eps * tick)))

            if debug:
                print(f"[tick] t={t_rel:6.2f}s {ename}: base_eps={base_eps:.2f} eff_eps={eff_eps:.2f} -> n={n}")

            # tick record (zawsze logujemy, nawet gdy n==0 — to ułatwia diagnostykę okien)
            now_epoch, now_iso = _now_epoch_iso()
            tick_rec = {
                "type": "tick",
                "emitter": ename,
                "n": n,
                "t_rel": t_rel,
                "ts": now_epoch,
                "ts_iso": now_iso,
                "base_eps": base_eps,
                "eff_eps": eff_eps,
                "in_window": in_window,
                "jitter_scale": jitter_scale,
                "schedule": {
                    "start_after_sec": start_after,
                    "stop_after_sec": stop_after,
                    "ramp_up_sec": ramp_up,
                    "ramp_down_sec": ramp_down,
                    "jitter_pct": jitter_pct,
                },
            }

            if n > 0:
                sent_approx[ename] += n

            if dry_run:
                _log_jsonl(logfh, tick_rec)
                continue

            if n <= 0:
                # w trybie live nic nie odpalamy przy n==0, ale i tak zapisujemy tick
                _log_jsonl(logfh, tick_rec)
                continue

            # uruchomienie emitera (plugin: ścieżka z YAML > mapa EMITTERS)
            script_path = e.get("script")  # może być None
            script = _resolve_script(ename, script_path)
            args = e.get("args", {})
            cmd = _build_cmd(py, script, n, args)

            rc, stdout, _ = _run_subprocess(cmd, step_timeout, debug)
            if rc == -2:
                print(f"[info] step '{ename}' interrupted (rc={rc})")
                _log_jsonl(logfh, {**tick_rec, "rc": rc, "levels": {}, "interrupted": True})
                break
            if strict and rc not in (0, 124):
                print(f"[error] step '{ename}' failed rc={rc}")
                errors_total[ename] += 1
                _log_jsonl(logfh, {"type": "error", "emitter": ename, "rc": rc, "ts": time.time(), "ts_iso": datetime.now(timezone.utc).isoformat()})
                # w strict – przerywamy całe scenario
                sys.exit(rc)
            elif rc not in (0, 124):
                errors_total[ename] += 1

            stat = _parse_sc_stat(stdout)
            lvl = (stat.get("level_counts") or {}) if isinstance(stat, dict) else {}
            for k, v in lvl.items():
                levels_total[ename][str(k).upper()] += int(v or 0)

            _log_jsonl(logfh, {**tick_rec, "rc": rc, "levels": lvl})

        if _STOP:
            break
        delay = tick - (time.time() - loop_start)
        if delay > 0:
            time.sleep(delay)

    print("[scenario] stopped gracefully.")
    print("[summary]")
    for ename in sorted(set([e["name"] for e in emitters])):
        approx = sent_approx.get(ename, 0)
        lvls = levels_total.get(ename, {})
        levels_str = ", ".join(f"{lvl}={cnt}" for lvl, cnt in sorted(lvls.items()))
        errs = errors_total.get(ename, 0)
        extra = f" | {levels_str}" if levels_str else ""
        if errs:
            extra += f" | errors={errs}"
        print(f"  {ename}: ~{approx} events (approx){extra}")

    end_epoch, end_iso = _now_epoch_iso()
    _log_jsonl(logfh, {
        "type": "scenario.end",
        "name": name,
        "ts": end_epoch,
        "ts_iso": end_iso,
        "sent_approx": dict(sent_approx),
        "levels_total": {k: dict(v) for k, v in levels_total.items()},
        "errors_total": dict(errors_total),
        "dry_run": dry_run,
    })
    if logfh:
        logfh.close()

def main():
    ap = argparse.ArgumentParser(description="Run LogOps traffic scenario (approx EPS) and aggregate level stats.")
    ap.add_argument("-s", "--scenario", required=True, help="Path to YAML scenario file")
    ap.add_argument("--py", default=sys.executable, help="Python interpreter to use for emitters")
    ap.add_argument("--strict", action="store_true", help="Fail if any emitter process returns non-zero (except timeout 124)")
    ap.add_argument("--step-timeout", type=float, default=20.0, help="Timeout per emitter invocation (seconds)")
    ap.add_argument("--dry-run", action="store_true", help="Simulate without running emitters")
    ap.add_argument("--debug", action="store_true", help="Verbose mode (print details)")
    ap.add_argument("--log-file", type=str, default=None, help="Write JSONL ticks/summary to this file")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for jitter/determinism")
    args = ap.parse_args()

    log_path = Path(args.log_file).resolve() if args.log_file else None
    run_scenario(
        Path(args.scenario).resolve(),
        py=args.py,
        strict=args.strict,
        step_timeout=args.step_timeout,
        dry_run=args.dry_run,
        debug=args.debug,
        log_file=log_path,
        seed=args.seed,
    )

if __name__ == "__main__":
    main()
