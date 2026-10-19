"""Read-only, local performance data. psutil is optional."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
from typing import Any

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


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
