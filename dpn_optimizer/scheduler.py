"""Explicit opt-in daily safe maintenance via Windows Task Scheduler."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

TASK = "DPN System Optimizer - Safe Daily Clean"


def _check_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Task scheduling is only supported on Windows.")


def task_status() -> tuple[bool, str]:
    _check_windows()
    try:
        p = subprocess.run(["schtasks.exe", "/Query", "/TN", TASK, "/FO", "LIST"],
                           capture_output=True, text=True, timeout=20, check=False)
        return p.returncode == 0, (p.stdout.strip() if p.returncode == 0 else "Not installed")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Unable to query Task Scheduler: {type(exc).__name__}"


def install_daily(script_path: Path, at_time: str = "09:00") -> str:
    _check_windows()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at_time):
        raise ValueError("Time must be HH:MM (24-hour clock).")
    script = script_path.resolve(strict=True)
    # The scheduled command deliberately cleans user Temp ONLY, age >= 48 h.
    # No administrator rights or elevated task token are requested.
    action = f'"{sys.executable}" "{script}" clean --apply --age-hours 48 --categories user_temp'
    proc = subprocess.run(["schtasks.exe", "/Create", "/SC", "DAILY",
                           "/ST", at_time, "/TN", TASK, "/TR", action,
                           "/RL", "LIMITED", "/F"], capture_output=True, text=True,
                          timeout=25, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "Failed to register task")
    return proc.stdout.strip()


def remove_daily() -> str:
    _check_windows()
    proc = subprocess.run(["schtasks.exe", "/Delete", "/TN", TASK, "/F"],
                          capture_output=True, text=True, timeout=25, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "Failed to remove task")
    return proc.stdout.strip()
