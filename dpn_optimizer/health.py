"""Windows built-in system integrity checks, manually triggered only."""
from __future__ import annotations
import os
import subprocess

TOOLS = {
    "sfc-verify": ["sfc.exe", "/verifyonly"],
    "dism-scan": ["DISM.exe", "/Online", "/Cleanup-Image", "/ScanHealth"],
}


def run_check(tool: str) -> tuple[int, str]:
    if os.name != "nt":
        raise RuntimeError("Windows health checks require Windows.")
    if tool not in TOOLS:
        raise ValueError("Only read-only verification is provided")
    try:
        # Long-running checks have a bounded runtime; no shell injection.
        proc = subprocess.run(TOOLS[tool], capture_output=True, text=True,
                              timeout=1800, errors="replace", check=False)
        return proc.returncode, (proc.stdout + "\n" + proc.stderr)[-12000:]
    except subprocess.TimeoutExpired:
        return 124, "Integrity scan exceeded 30 minutes; check Windows logs for details."
    except OSError as exc:
        return 1, f"Could not launch integrity check: {type(exc).__name__}"
