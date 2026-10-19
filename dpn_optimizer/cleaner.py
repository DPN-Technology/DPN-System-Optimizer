"""Conservative Windows cleanup, with explicit categories and preview-first behavior.

Never follows file-system links/junctions; never deletes an approved root; never
recursively removes populated directories. Browser caches require closed browsers.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import __version__

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
CATEGORIES = {
    "user_temp": "User temporary files",
    "shader_cache": "DirectX shader cache",
    "crash_reports": "Old crash reports (optional)",
    "browser_cache": "Chrome / Edge cache (optional)",
    "system_temp": "Windows temp (admin may be required)",
}
DEFAULT_CATEGORIES = ("user_temp",)


def human_bytes(number: int | float) -> str:
    value = float(number)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


def app_data_dir() -> Path:
    return local_appdata() / "DPN Technology" / "System Optimizer"


def is_unsafe_link(path: Path) -> bool:
    """Fail closed if a path is missing/inaccessible or is a link/junction."""
    try:
        st = path.lstat()
        return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE)
    except OSError:
        return True


def _safe_root(path: Path, trusted_base: Path) -> Path | None:
    """Validate all ancestor directories from trusted base through candidate."""
    try:
        base = trusted_base.expanduser().absolute()
        candidate = path.expanduser().absolute()
        rel = candidate.relative_to(base)
        if not rel.parts or not candidate.is_dir():
            return None
        if is_unsafe_link(base):
            return None
        cursor = base
        for part in rel.parts:
            cursor = cursor / part
            if is_unsafe_link(cursor):
                return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base.resolve(strict=True))
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


@dataclass(frozen=True)
class Root:
    category: str
    name: str
    path: Path


def roots_for(categories: Iterable[str]) -> tuple[list[Root], list[str]]:
    """Only internally enumerated, fixed cleanup locations. Never arbitrary input."""
    selected = set(categories)
    if unknown := selected - CATEGORIES.keys():
        raise ValueError(f"Unknown categories: {', '.join(sorted(unknown))}")
    local = local_appdata()
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates: list[tuple[str, str, Path, Path]] = []
    if "user_temp" in selected:
        candidates.append(("user_temp", "User temp", local / "Temp", local))
    if "shader_cache" in selected:
        candidates.append(("shader_cache", "DirectX shader cache", local / "D3DSCache", local))
    if "crash_reports" in selected:
        for sub in ("ReportArchive", "ReportQueue"):
            candidates.append(("crash_reports", f"Windows Error Reporting / {sub}",
                               local / "Microsoft" / "Windows" / "WER" / sub, local))
        candidates.append(("crash_reports", "User crash dumps", local / "CrashDumps", local))
    if "system_temp" in selected:
        candidates.append(("system_temp", "Windows temp", windir / "Temp", windir))
    if "browser_cache" in selected:
        for browser, basedir in (("Chrome", local / "Google" / "Chrome" / "User Data"),
                                 ("Edge", local / "Microsoft" / "Edge" / "User Data")):
            # Only profile names Chrome/Edge normally create. Do not recursively
            # search their data folders or touch passwords, cookies, or history.
            profiles: list[Path] = []
            try:
                if basedir.is_dir() and not is_unsafe_link(basedir):
                    profiles = [p for p in basedir.iterdir()
                                if p.is_dir() and not is_unsafe_link(p) and
                                (p.name == "Default" or re.fullmatch(r"Profile \d+", p.name))]
            except OSError:
                pass
            for profile in profiles:
                for rel in (("Cache", "Cache_Data"), ("Cache",),
                            ("Code Cache", "js"), ("Code Cache", "wasm"),
                            ("GPUCache",)):
                    directory = profile.joinpath(*rel)
                    candidates.append(("browser_cache", f"{browser} / {profile.name} / {'/'.join(rel)}",
                                       directory, local))
    roots, skipped, seen = [], [], set()
    for category, label, path, base in candidates:
        valid = _safe_root(path, base)
        if valid is None:
            # Not installed/not present is normal; no need to alarm.
            continue
        key = os.path.normcase(str(valid)).casefold()
        if key in seen:
            continue
        seen.add(key)
        roots.append(Root(category, label, valid))
    return roots, skipped


def browsers_running() -> tuple[bool, str]:
    """Fail closed if we cannot reliably verify all browsers are shut."""
    try:
        import psutil  # type: ignore
        names = {str(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
        active = sorted(names.intersection({"chrome.exe", "msedge.exe"}))
        return bool(active), ", ".join(active)
    except ImportError:
        if os.name != "nt":
            return True, "Unable to verify browser process state"
        try:
            p = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=12, check=True)
            import csv
            names = {row[0].lower() for row in csv.reader(p.stdout.splitlines()) if row}
            active = sorted(names.intersection({"chrome.exe", "msedge.exe"}))
            return bool(active), ", ".join(active)
        except (OSError, subprocess.SubprocessError, IndexError):
            return True, "Browser state could not be verified"
    except Exception:
        return True, "Browser state could not be verified"


def file_age(st: os.stat_result) -> float:
    return max(st.st_mtime, st.st_ctime) if os.name == "nt" else st.st_mtime


def _stats(name: str, category: str) -> dict[str, Any]:
    return {"name": name, "category": category, "scanned": 0, "eligible_files": 0,
            "eligible_bytes": 0, "deleted_files": 0, "deleted_bytes": 0,
            "skipped_recent": 0, "skipped_links": 0, "errors": 0,
            "empty_dirs_removed": 0}


def clean_root(root: Root, cutoff: float, apply: bool,
               cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Iterative scan; skip reparse points; re-stat before removal. No root deletion."""
    stats = _stats(root.name, root.category)
    if not root.path.is_dir() or is_unsafe_link(root.path):
        stats["errors"] += 1
        return stats
    stack = [root.path]
    child_dirs: list[Path] = []
    while stack:
        if cancelled and cancelled():
            stats["cancelled"] = True
            break
        directory = stack.pop()
        if is_unsafe_link(directory):
            stats["skipped_links"] += 1
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancelled and cancelled():
                        stats["cancelled"] = True
                        break
                    path = Path(entry.path)
                    try:
                        if entry.is_symlink() or is_unsafe_link(path):
                            stats["skipped_links"] += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            child_dirs.append(path)
                            stack.append(path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                        stats["scanned"] += 1
                        if file_age(st) > cutoff:
                            stats["skipped_recent"] += 1
                            continue
                        stats["eligible_files"] += 1
                        stats["eligible_bytes"] += st.st_size
                        if apply:
                            current = path.lstat()
                            if is_unsafe_link(path) or not stat.S_ISREG(current.st_mode):
                                stats["skipped_links"] += 1
                                continue
                            if file_age(current) > cutoff:
                                stats["skipped_recent"] += 1
                                continue
                            # Do not delete a file that changed during scanning.
                            if current.st_mtime_ns != st.st_mtime_ns or current.st_size != st.st_size:
                                stats["skipped_recent"] += 1
                                continue
                            path.unlink()
                            stats["deleted_files"] += 1
                            stats["deleted_bytes"] += current.st_size
                    except OSError:
                        stats["errors"] += 1  # locked/access denied: leave intact
        except OSError:
            stats["errors"] += 1
        if stats.get("cancelled"):
            break
    if apply and not stats.get("cancelled"):
        for d in sorted(child_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                if not is_unsafe_link(d):
                    d.rmdir()  # removes only empty child directories
                    stats["empty_dirs_removed"] += 1
            except OSError:
                pass
    return stats


def run_cleanup(categories: Iterable[str] = DEFAULT_CATEGORIES, *,
                age_hours: float = 48, apply: bool = False,
                notify: Callable[[str], None] | None = None,
                cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    if not 1 <= age_hours <= 8760:
        raise ValueError("Age must be between 1 and 8760 hours")
    selected = tuple(dict.fromkeys(categories))
    if not selected:
        raise ValueError("Select at least one cleanup category")
    roots, skipped = roots_for(selected)
    if "browser_cache" in selected:
        running, reason = browsers_running()
        if running:
            roots = [r for r in roots if r.category != "browser_cache"]
            skipped.append(f"Browser cache skipped: {reason or 'Browser is running'}")
    results = []
    cutoff = time.time() - age_hours * 3600
    for root in roots:
        if cancelled and cancelled():
            skipped.append("Operation cancelled")
            break
        if notify:
            notify(f"{'Cleaning' if apply else 'Scanning'}: {root.name}")
        results.append(clean_root(root, cutoff, apply, cancelled=cancelled))
        if results[-1].get("cancelled"):
            skipped.append("Operation cancelled")
            break
    totals = {k: sum(r[k] for r in results) for k in
              ("scanned", "eligible_files", "eligible_bytes", "deleted_files",
               "deleted_bytes", "skipped_recent", "skipped_links", "errors", "empty_dirs_removed")}
    report = {"app": "DPN System Optimizer", "version": __version__,
              "when": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "action": "clean" if apply else "preview", "age_hours": age_hours,
              "categories": list(selected), "roots_scanned": len(results),
              "skipped": skipped, "totals": totals, "breakdown": results}
    try:
        save_report(report)
    except OSError:
        if notify:
            notify("Report could not be written; cleanup results are available here.")
    return report


def reports_path() -> Path:
    return app_data_dir() / "Reports"


def save_report(report: dict[str, Any]) -> Path:
    folder = reports_path()
    folder.mkdir(parents=True, exist_ok=True)
    # Reports omit file names/paths; do not log file content.
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = folder / f"DPN-{report.get('action', 'report')}-{stamp}.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    try:
        paths = sorted(reports_path().glob("DPN-*.json"), reverse=True)[:limit]
    except OSError:
        return []
    result = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                result.append(data)
        except (OSError, ValueError, UnicodeError):
            continue
    return result
