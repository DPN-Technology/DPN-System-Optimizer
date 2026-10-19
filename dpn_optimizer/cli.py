"""CLI for DPN System Optimizer v2.0."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .cleaner import (CATEGORIES, DEFAULT_CATEGORIES, human_bytes, list_reports,
                      reports_path, run_cleanup)
from .diagnostics import performance_advice, performance_snapshot
from .startup import list_startup_items
from . import scheduler, health


def format_report(report: dict) -> str:
    t = report["totals"]
    lines = ["=" * 64, f"DPN TECHNOLOGY // SYSTEM OPTIMIZER v{__version__}",
             "=" * 64,
             f"Mode: {report['action'].upper()} | Age: {report['age_hours']}h | Roots: {report['roots_scanned']}",
             f"Examined: {t['scanned']} files | Eligible: {t['eligible_files']} ({human_bytes(t['eligible_bytes'])})",
             f"Removed: {t['deleted_files']} files ({human_bytes(t['deleted_bytes'])})",
             f"Skipped: {t['skipped_recent']} recent, {t['skipped_links']} links, {t['errors']} errors"]
    for r in report["breakdown"]:
        lines.append(f"  {r['name']}: {r['eligible_files']} eligible, {r['deleted_files']} removed")
    for s in report.get("skipped", []):
        lines.append(f"  NOTICE: {s}")
    lines += [f"Reports: {reports_path()}", "Cleanup frees space; it does not automatically boost CPU/RAM."]
    return "\n".join(lines)


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DPN System Optimizer v2.0 — safe Windows maintenance")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("gui", help="Launch the graphical dashboard")
    diag = sub.add_parser("diagnose", help="Display CPU/RAM/disk status and top memory processes")
    diag.add_argument("--json", action="store_true", help="Print machine-readable JSON for DPN automation")
    sub.add_parser("startup", help="Read-only startup inventory")
    for command in ("preview", "clean"):
        q = sub.add_parser(command, help="Preview or clean selected old files")
        q.add_argument("--categories", nargs="+", choices=sorted(CATEGORIES), default=list(DEFAULT_CATEGORIES))
        q.add_argument("--age-hours", type=float, default=48)
        if command == "clean":
            q.add_argument("--apply", action="store_true", help="Actually delete selected old files")
    sub.add_parser("history", help="Show recent cleanup reports")
    h = sub.add_parser("health", help="Optional read-only Windows integrity checks")
    h.add_argument("tool", choices=tuple(health.TOOLS))
    s = sub.add_parser("schedule", help="Manage opt-in daily user-temp cleanup task")
    s.add_argument("action", choices=("status", "install", "remove"))
    s.add_argument("--time", default="09:00", help="Local time HH:MM for daily cleanup")
    return p


def main(argv: list[str] | None = None, script_path: Path | None = None) -> int:
    args = make_parser().parse_args(argv)
    script_path = script_path or Path(sys.argv[0])
    if args.command in (None, "gui"):
        if os.name != "nt":
            print("GUI is intended for Windows 10/11. Run --help for commands.")
            return 2
        try:
            from .gui import launch_gui
            launch_gui(script_path)
            return 0
        except ImportError as exc:
            print(f"Tkinter not available: {exc}. Use CLI commands instead.")
            return 2
    if args.command == "diagnose":
        snapshot = performance_snapshot()
        if args.json:
            print(json.dumps({"snapshot": snapshot, "recommendations": performance_advice(snapshot)},
                             indent=2))
            return 0
        d, m = snapshot["disk"], snapshot["ram"]
        print("\nDPN // PERFORMANCE SNAPSHOT")
        print("CPU:", f"{snapshot['cpu']}%" if snapshot["cpu"] is not None else "psutil required")
        if m:
            print(f"RAM: {m['percent']}% used, {human_bytes(m['available'])} available")
        if d:
            print(f"Disk: {d['percent']}% used, {human_bytes(d['free'])} free")
        for proc in snapshot["top_processes"][:10]:
            print(f"  PID {proc['pid']:<7} {proc['name'][:34]:<34} {human_bytes(proc['ram_bytes']):>10}")
        print("\nRecommendations:")
        for message in performance_advice(snapshot):
            print(" -", message)
        return 0
    if args.command == "startup":
        if os.name != "nt":
            print("Windows only.")
            return 2
        for item in list_startup_items():
            print(f"[{item['source']}] {item['name']} -> {item['command']}")
        print("Read-only. Use Windows Settings > Apps > Startup to disable unwanted entries.")
        return 0
    if args.command in ("preview", "clean"):
        if os.name != "nt":
            print("Cleanup is available on Windows 10/11 only.")
            return 2
        apply = args.command == "clean" and args.apply
        try:
            r = run_cleanup(args.categories, age_hours=args.age_hours, apply=apply,
                            notify=lambda msg: print(msg, flush=True))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(format_report(r))
        if args.command == "clean" and not apply:
            print("NO FILES DELETED: add --apply to explicitly authorize cleanup.")
        return 0
    if args.command == "history":
        reports = list_reports(limit=20)
        if not reports:
            print("No reports yet.")
        for r in reports:
            t = r.get("totals", {})
            print(f"{r.get('when')} | {r.get('action')} | "
                  f"Eligible {human_bytes(t.get('eligible_bytes', 0))} | "
                  f"Removed {human_bytes(t.get('deleted_bytes', 0))}")
        print(f"Folder: {reports_path()}")
        return 0
    if args.command == "health":
        try:
            print(f"Running Windows verification: {args.tool}. This may take a while.", flush=True)
            code, output = health.run_check(args.tool)
            print(output)
            return code
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
    if args.command == "schedule":
        try:
            if args.action == "status":
                present, detail = scheduler.task_status()
                print("Scheduled:" if present else "Not scheduled:", detail)
            elif args.action == "install":
                print(scheduler.install_daily(script_path, args.time))
                print("Installed: daily USER TEMP cleanup only, age >= 48 h; runs with limited privileges.")
            elif args.action == "remove":
                print(scheduler.remove_daily())
            return 0
        except (RuntimeError, ValueError, OSError) as exc:
            print(exc, file=sys.stderr)
            return 2
    return 2
