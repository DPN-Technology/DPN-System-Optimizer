#!/usr/bin/env python3
"""DPN Technology System Optimizer v2.0. Windows 10/11, Python >= 3.10.

Double-click START_DPN_OPTIMIZER.bat for the GUI, or use --help for CLI.
No files are deleted without an explicit clean --apply / GUI confirmation.
"""
from pathlib import Path
import sys
from dpn_optimizer.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], Path(__file__).resolve()))
