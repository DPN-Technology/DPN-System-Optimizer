"""Read-only inventory of Windows Run registry values and Startup shortcuts."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_POTENTIALLY_HIGH_IMPACT = (
    "onedrive", "dropbox", "google drive", "icloud", "teams", "discord",
    "slack", "zoom", "webex", "steam", "epic games", "spotify",
    "creative cloud",
)


def assess_startup_item(name: str, command: str) -> dict[str, str]:
    """Give cautious heuristic labels; startup time and signer are not measured."""
    searchable = f"{name} {command}".casefold()
    impact = "Potentially high" if any(
        app in searchable for app in _POTENTIALLY_HIGH_IMPACT
    ) else "Unrated"
    return {
        "impact": impact,
        "publisher": "Unknown (not verified)",
    }


def list_startup_items() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    import winreg
    keys = [
        ("HKCU", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ("HKCU Once", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ("HKLM Once", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ]
    flags = [0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY]
    items: list[dict[str, Any]] = []
    seen = set()
    for name, hive, key_name in keys:
        for view in flags:
            try:
                with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    for index in range(count):
                        try:
                            label, command, _ = winreg.EnumValue(key, index)
                        except OSError:
                            continue
                        marker = (name, label, str(command))
                        if marker in seen:
                            continue
                        seen.add(marker)
                        command_text = str(command)[:400]
                        items.append({"source": name + " Run key", "name": label,
                                      "command": command_text,
                                      **assess_startup_item(label, command_text)})
            except OSError:
                continue
    folder_candidates = (
        ("User Startup folder", Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) /
         "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"),
        ("All Users Startup folder", Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) /
         "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"),
    )
    for label, folder in folder_candidates:
        try:
            for child in folder.iterdir():
                if child.is_file() and not child.is_symlink():
                    command = "Shortcut/file in Startup folder (not executed)"
                    items.append({"source": label, "name": child.name,
                                  "command": command,
                                  **assess_startup_item(child.name, command)})
        except OSError:
            continue
    return sorted(items, key=lambda i: (i["source"], i["name"].lower()))
