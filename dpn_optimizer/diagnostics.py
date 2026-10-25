"""Read-only, local performance data. psutil is optional."""
from __future__ import annotations

import os
import getpass
from pathlib import Path
import platform
import shutil
from typing import Any

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


class ProcessActionError(RuntimeError):
    """A process could not be safely inspected or ended."""


_PROTECTED_PROCESS_NAMES = {
    "csrss.exe", "dwm.exe", "explorer.exe", "lsass.exe", "registry",
    "services.exe", "smss.exe", "svchost.exe", "system", "system idle process",
    "wininit.exe", "winlogon.exe",
}


def list_process_details() -> list[dict[str, Any]]:
    """Return a best-effort local process snapshot for the process explorer."""
    if psutil is None:
        raise RuntimeError("Install optional psutil to use the process explorer.")
    processes = []
    try:
        for proc in psutil.process_iter(
            ["pid", "name", "username", "memory_info", "memory_percent", "exe",
             "create_time", "status"]
        ):
            try:
                info = proc.info
                memory = info.get("memory_info")
                name = info.get("name") or "unknown"
                username = info.get("username") or ""
                executable = info.get("exe") or ""
                processes.append({
                    "pid": info["pid"],
                    "name": name,
                    "username": username or "Unavailable",
                    "cpu_percent": max(0.0, float(proc.cpu_percent(interval=None))),
                    "memory_percent": float(info.get("memory_percent") or 0),
                    "ram_bytes": memory.rss if memory else 0,
                    "exe": executable,
                    "create_time": info.get("create_time") or 0.0,
                    "status": info.get("status") or "unknown",
                    "can_end": (
                        info["pid"] > 4
                        and info["pid"] != os.getpid()
                        and bool(username)
                        and _user_key(username) == _user_key(getpass.getuser())
                        and name.casefold() not in _PROTECTED_PROCESS_NAMES
                        and bool(executable)
                        and not _is_windows_directory(executable)
                    ),
                })
            except (psutil.Error, OSError, ValueError):
                continue
    except psutil.Error as exc:
        raise RuntimeError(f"Could not enumerate processes: {exc}") from exc
    return sorted(
        processes,
        key=lambda item: (item["cpu_percent"], item["ram_bytes"]),
        reverse=True,
    )


def _user_key(username: str) -> str:
    return username.rsplit("\\", 1)[-1].split("@", 1)[0].casefold()


def _is_windows_directory(executable: str) -> bool:
    windows_root = os.path.abspath(os.environ.get("SystemRoot", r"C:\Windows"))
    executable = os.path.abspath(executable)
    try:
        return os.path.commonpath((windows_root, executable)).casefold() == windows_root.casefold()
    except ValueError:
        return False


def terminate_user_process(
    pid: int,
    expected_name: str,
    expected_create_time: float,
    expected_username: str,
) -> None:
    """End a confirmed process only if it is still the same user's same process.

    This intentionally refuses system processes, protected Windows components,
    and executables under the Windows directory. Windows termination is
    immediate, so callers must confirm the user understands unsaved work may
    be lost.
    """
    if psutil is None:
        raise ProcessActionError("Install optional psutil to end a process.")
    if pid <= 4 or pid == os.getpid():
        raise ProcessActionError("Protected system or application process.")

    try:
        proc = psutil.Process(pid)
        name = proc.name()
        username = proc.username()
        executable = proc.exe()
        created = proc.create_time()
        if not proc.is_running():
            raise ProcessActionError("That process has already exited.")
    except psutil.NoSuchProcess as exc:
        raise ProcessActionError("That process has already exited.") from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise ProcessActionError("The process identity cannot be verified; no action was taken.") from exc

    if name.casefold() in _PROTECTED_PROCESS_NAMES or _is_windows_directory(executable):
        raise ProcessActionError("Windows or protected processes cannot be ended here.")
    current_user = getpass.getuser()
    if (not username or _user_key(username) != _user_key(current_user)
            or _user_key(username) != _user_key(expected_username)):
        raise ProcessActionError("Only a verified process owned by the current user can be ended.")
    if name.casefold() != expected_name.casefold():
        raise ProcessActionError("The process changed since the list was refreshed.")
    if abs(created - expected_create_time) > 0.01:
        raise ProcessActionError("The process changed since the list was refreshed.")

    try:
        proc.terminate()
    except psutil.NoSuchProcess as exc:
        raise ProcessActionError("That process exited before the action completed.") from exc
    except (psutil.AccessDenied, OSError) as exc:
        raise ProcessActionError("Windows denied the request; no action was taken.") from exc


def performance_health_score(snapshot: dict[str, Any]) -> int | None:
    """Return a simple headroom score for the available CPU, RAM, and disk samples."""
    usage = []
    if snapshot.get("cpu") is not None:
        usage.append(snapshot["cpu"])
    if snapshot.get("ram") is not None:
        usage.append(snapshot["ram"]["percent"])
    if snapshot.get("disk") is not None:
        usage.append(snapshot["disk"]["percent"])
    if not usage:
        return None
    headroom = [100 - max(0.0, min(100.0, float(value))) for value in usage]
    return round(sum(headroom) / len(headroom))


def performance_snapshot() -> dict[str, Any]:
    disk_root = Path(os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else Path.home()
    try:
        d = shutil.disk_usage(disk_root)
        disk = {"total": d.total, "used": d.used, "free": d.free,
                "percent": round(d.used / d.total * 100, 1) if d.total else 0}
    except OSError:
        disk = None
    data: dict[str, Any] = {"os": platform.platform(), "hostname": platform.node(),
                            "disk": disk, "cpu": None, "ram": None,
                            "top_processes": [], "monitoring_available": psutil is not None}
    if psutil is not None:
        try:
            v = psutil.virtual_memory()
            data["cpu"] = round(psutil.cpu_percent(interval=0.1), 1)
            data["ram"] = {"total": v.total, "used": v.used,
                           "available": v.available, "percent": round(v.percent, 1)}
            top = []
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    info = proc.info
                    rss = info["memory_info"].rss if info.get("memory_info") else 0
                    top.append({"pid": info["pid"], "name": info.get("name") or "unknown", "ram_bytes": rss})
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
            data["top_processes"] = sorted(top, key=lambda p: p["ram_bytes"], reverse=True)[:12]
        except (psutil.Error, OSError):
            pass
    else:
        # WinAPI read-only RAM measurement if optional psutil isn't installed.
        if os.name == "nt":
            try:
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                                ("ullAvailExtended", ctypes.c_ulonglong)]
                mem = MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(mem)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                    data["ram"] = {"total": mem.ullTotalPhys,
                                   "used": mem.ullTotalPhys - mem.ullAvailPhys,
                                   "available": mem.ullAvailPhys, "percent": int(mem.dwMemoryLoad)}
            except (AttributeError, OSError):
                pass
    return data


def performance_advice(snapshot: dict[str, Any]) -> list[str]:
    messages = []
    disk, ram = snapshot.get("disk"), snapshot.get("ram")
    if disk is not None and (disk["free"] < 15 * 1024**3 or disk["percent"] >= 90):
        messages.append("Disk space is low: consider removing unused applications or moving personal files.")
    if ram is not None and ram["percent"] >= 85:
        messages.append("Memory pressure is high: review the top memory consumers before closing anything.")
    if snapshot.get("cpu") is not None and snapshot["cpu"] >= 85:
        messages.append("CPU use is high in this sample: check Task Manager for sustained use.")
    if not snapshot["monitoring_available"]:
        messages.append("Install the free 'psutil' package for CPU monitoring and a process list.")
    if not messages:
        messages.append("No major bottleneck detected in this snapshot; monitor trends before making changes.")
    return messages
