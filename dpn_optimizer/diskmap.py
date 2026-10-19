"""Read-only disk usage analysis: where space goes and which files are largest.

Nothing here modifies or deletes files. Symlinks and Windows reparse points are
never followed, so the scan cannot escape the chosen root or loop.
"""
from __future__ import annotations

import heapq
import os
import stat
import time
from pathlib import Path
from typing import Any, Callable

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & REPARSE)
    except OSError:
        return True


def scan_disk_usage(root: Path, top_files: int = 25, max_seconds: float = 45.0,
                    cancelled: Callable[[], bool] = lambda: False,
                    progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Sum file sizes under `root`, grouped by its immediate children.

    The scan stops early (``truncated`` is True) when cancelled or after
    `max_seconds`, and the totals then cover only what was visited.
    """
    root = Path(root)
    started = time.monotonic()
    groups: dict[str, int] = {}
    loose_files = 0
    files_seen = errors = 0
    largest: list[tuple[int, str]] = []
    truncated = False

    try:
        top_entries = list(os.scandir(root))
    except OSError as exc:
        raise ValueError(f"Cannot read {root}: {type(exc).__name__}") from exc

    for top in top_entries:
        if _is_link(top):
            continue
        try:
            is_dir = top.is_dir(follow_symlinks=False)
        except OSError:
            errors += 1
            continue
        if not is_dir:
            try:
                size = top.stat(follow_symlinks=False).st_size
            except OSError:
                errors += 1
                continue
            loose_files += size
            files_seen += 1
            heapq.heappush(largest, (size, top.path))
            if len(largest) > top_files:
                heapq.heappop(largest)
            continue
        total = 0
        pending = [top.path]
        while pending:
            if cancelled() or time.monotonic() - started > max_seconds:
                truncated = True
                break
            current = pending.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if _is_link(entry):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(entry.path)
                                continue
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            errors += 1
                            continue
                        total += size
                        files_seen += 1
                        heapq.heappush(largest, (size, entry.path))
                        if len(largest) > top_files:
                            heapq.heappop(largest)
            except OSError:
                errors += 1
        groups[top.name] = total
        if progress:
            progress(files_seen)
        if truncated:
            break

    if loose_files:
        groups["(files in root)"] = loose_files
    grand_total = sum(groups.values())
    folders = [{"name": name, "bytes": size,
                "percent": round(size / grand_total * 100, 1) if grand_total else 0.0}
               for name, size in sorted(groups.items(), key=lambda kv: kv[1], reverse=True)]
    return {
        "root": str(root),
        "total_bytes": grand_total,
        "files_seen": files_seen,
        "errors": errors,
        "truncated": truncated,
        "folders": folders,
        "largest_files": [{"path": path, "bytes": size}
                          for size, path in sorted(largest, reverse=True)],
    }
