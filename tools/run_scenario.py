# tools/run_scenario.py
import argparse, subprocess, sys, time, yaml, shlex, signal, json, re
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[1]

# Mapowanie „nazw emiterów” -> ścieżki do skryptów
EMITTERS = {
    "emitter_csv":     "emitters/emitter_csv/emit_csv.py",
    "emitter_json":    "emitters/emitter_json/emit_json.py",
    "emitter_minimal": "emitters/emitter_minimal/emit_minimal.py",
    "emitter_noise":   "emitters/emitter_noise/emit_noise.py",
    "emitter_syslog":  "emitters/emitter_syslog/emit_syslog.py",
}

# linia statów wypisywana przez emitery:  SC_STAT {...}
SC_STAT_RE = re.compile(r"^\s*SC_STAT\s+(?P<json>\{.*\})\s*$")

# ————— globalny „stop” po SIGINT —————
_STOP = False
def _on_sigint(sig, frame):
    global _STOP
    _STOP = True
    print("[scenario] SIGINT received, stopping gracefully after current tick...", flush=True)

signal.signal(signal.SIGINT, _on_sigint)

def _resolve_script(emitter_name: str) -> Path:
    rel = EMITTERS.get(emitter_name)
    if not rel:
        raise RuntimeError(f"Unknown emitter: {emitter_name}")
    p = ROOT / rel
    if not p.exists():
        raise RuntimeError(f"Emitter script not found: {p}")
    return p

def _build_cmd(py: str, script: Path, n: int, args: dict) -> list[str]:
    cmd = [py, str(script), "-n", str(n)]
    # ujednolicone argumenty wspólne dla emiterów
    if "partial_ratio" in args:
        cmd += ["--partial-ratio", str(args["partial_ratio"])]
    if "chaos" in args:
        cmd += ["--chaos", str(args["chaos"])]
    if "seed" in args and args["seed"] is not None:
        cmd += ["--seed", str(args["seed"])]
    return cmd

def _run_once(py: str, emitter_name: str, n: int, args: dict, step_timeout: float | None):
    """
    Uruchamia pojedynczy emiter i zwraca tuple:
    (return_code, stdout, stderr)
    """
    script = _resolve_script(emitter_name)
    cmd = _build_cmd(py, script, n, args)
    print(">>", " ".join(shlex.quote(c) for c in cmd), flush=True)
    try:
        out = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=step_timeout,
        )
        # pokaż „nagłówki” ze standardowego wyjścia emiterów
        if out.stdout:
            sys.stdout.write(out.stdout)
            sys.stdout.flush()
        if out.stderr:
            sys.stderr.write(out.stderr)
            sys.stderr.flush()
        return out.returncode, (out.stdout or ""), (out.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"[warn] step '{emitter_name}' timed out (>{step_timeout}s), continuing...", flush=True)
        return 124, "", ""
    except KeyboardInterrupt:
        # SIGINT obsługujemy globalnie, ale subprocess też może dostać
        return -2, "", ""

def _parse_sc_stat(stdout: str) -> dict:
    """
    Z emiterowego stdout wyciąga ostatni SC_STAT {...} (jeśli jest) i zwraca dict.
    """
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

def run_scenario(scn_path: Path, py: str, strict: bool, step_timeout: float | None):
    with open(scn_path, "r", encoding="utf-8") as fh:
        scn = yaml.safe_load(fh)

    name = scn.get("name", scn_path.stem)
    duration = float(scn.get("duration_sec", 30))
    tick = float(scn.get("tick_sec", 1.0))
    emitters = scn.get("emitters", [])

    # Akumulatory
    sent_approx = Counter()                      # per-emitter ~liczba eventów
    levels_total = defaultdict(Counter)          # per-emitter: Counter(level->count)

    print(f"[scenario] {name} | duration={duration:.0f}s tick={tick:.2f}s emitters={len(emitters)}")

    started = time.time()
    while (time.time() - started) < duration and not _STOP:
        loop_start = time.time()
        for e in emitters:
            ename = e["name"]
            eps = float(e.get("eps", 10.0))
            n = max(0, int(round(eps * tick)))
            if n <= 0:
                continue

            rc, stdout, _ = _run_once(py, ename, n, e.get("args", {}), step_timeout)
            if rc == -2:
                print(f"[info] step '{ename}' interrupted (rc={rc})")
                break
            if strict and rc not in (0, 124):
                print(f"[error] step '{ename}' failed rc={rc}")
                sys.exit(rc)

            # przyjmujemy, że jeśli emiter działa, to „próbował” wysłać n rekordów
            sent_approx[ename] += n

            # spróbuj wczytać staty z SC_STAT
            stat = _parse_sc_stat(stdout)
            lvl = (stat.get("level_counts") or {}) if isinstance(stat, dict) else {}
            for k, v in lvl.items():
                # Normalizujemy nazwy leveli „na wszelki wypadek”
                levels_total[ename][str(k).upper()] += int(v or 0)

        # domknij tick
        if _STOP:
            break
        delay = tick - (time.time() - loop_start)
        if delay > 0:
            time.sleep(delay)

    print("[scenario] stopped gracefully.")
    print("[summary]")
    # per-emitter
    for ename in EMITTERS.keys():
        if ename in sent_approx or ename in levels_total:
            approx = sent_approx.get(ename, 0)
            lvls = levels_total.get(ename, {})
            # drukuj tylko level-e które miały sensowne wartości
            levels_str = ", ".join(f"{lvl}={cnt}" for lvl, cnt in sorted(lvls.items()))
            print(f"  {ename}: ~{approx} events (approx){(' | ' + levels_str) if levels_str else ''}")

def main():
    ap = argparse.ArgumentParser(description="Run LogOps traffic scenario (approx EPS) and aggregate level stats.")
    ap.add_argument("-s", "--scenario", required=True, help="Path to YAML scenario file")
    ap.add_argument("--py", default=sys.executable, help="Python interpreter to use for emitters")
    ap.add_argument("--strict", action="store_true", help="Fail if any emitter process returns non-zero (except timeout 124)")
    ap.add_argument("--step-timeout", type=float, default=20.0, help="Timeout per emitter invocation (seconds)")
    args = ap.parse_args()
    run_scenario(Path(args.scenario).resolve(), py=args.py, strict=args.strict, step_timeout=args.step_timeout)

if __name__ == "__main__":
    main()
