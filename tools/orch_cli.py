#!/usr/bin/env python3
import argparse
import json
import urllib.request

BASE = "http://127.0.0.1:8070"


def _req(path, data=None):
    url = BASE + path
    if data is None:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read().decode())
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def cmd_list(_):
    out = _req("/scenario/list")
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_start(args):
    payload = {}
    if args.name:
        payload["name"] = args.name
    if args.yaml_path:
        payload["yaml_path"] = args.yaml_path
    if args.inline:
        payload["inline"] = json.loads(args.inline)
    payload["dry_run"] = args.dry_run
    payload["debug"] = args.debug
    payload["strict"] = args.strict
    if args.seed is not None:
        payload["seed"] = args.seed
    payload["step_timeout_sec"] = args.step_timeout
    out = _req("/scenario/start", payload)
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_stop(args):
    out = _req("/scenario/stop", {"scenario_id": args.scenario_id})
    print(json.dumps(out, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Orchestrator CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("list")
    s1.set_defaults(func=cmd_list)

    s2 = sub.add_parser("start")
    s2.add_argument("--name")
    s2.add_argument("--yaml-path")
    s2.add_argument("--inline", help="JSON string with scenario body")
    s2.add_argument("--seed", type=int)
    s2.add_argument("--dry-run", action="store_true")
    s2.add_argument("--debug", action="store_true")
    s2.add_argument("--strict", action="store_true")
    s2.add_argument("--step-timeout", type=float, default=20.0)
    s2.set_defaults(func=cmd_start)

    s3 = sub.add_parser("stop")
    s3.add_argument("scenario_id")
    s3.set_defaults(func=cmd_stop)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
