"""Read-only disk usage analysis: where space goes and which files are largest.

Nothing here modifies or deletes files. Symlinks and Windows reparse points are
never followed, so the scan cannot escape the chosen root or loop.
"""
from __future__ import annotations

import heapq
import hashlib
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


def scan_file_insights(
    root: Path,
    min_size: int = 1 * 1024 * 1024,
    top_files: int = 50,
    max_seconds: float = 90.0,
    max_candidates: int = 50_000,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Find large files and exact duplicates without changing any files.

    Candidate files are grouped by size before hashing, avoiding content reads
    for files that cannot possibly be duplicates. Both traversal and hashing
    are bounded by time, candidate count, and the caller's cancellation flag.
    """
    if min_size < 0:
        raise ValueError("Minimum file size cannot be negative.")
    if top_files < 1 or max_candidates < 1 or max_seconds <= 0:
        raise ValueError("Scan limits must be positive.")

    root = Path(root)
    started = time.monotonic()
    pending = [root]
    candidates: dict[int, list[tuple[str, int, int]]] = {}
    candidate_count = 0
    largest: list[tuple[int, str]] = []
    files_seen = errors = 0
    truncated = False

    try:
        if not root.is_dir():
            raise OSError("not a directory")
        root.stat()
    except OSError as exc:
        raise ValueError(f"Cannot read {root}: {type(exc).__name__}") from exc

    while pending:
        if cancelled() or time.monotonic() - started >= max_seconds:
            truncated = True
            break
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancelled() or time.monotonic() - started >= max_seconds:
                        truncated = True
                        break
                    if _is_link(entry):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                            continue
                        # Windows DirEntry.stat can report zero for st_dev/st_ino;
                        # os.stat supplies the identity needed to avoid overcounting
                        # hard links in the reclaimable-space estimate.
                        info = os.stat(entry.path, follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        size = info.st_size
                        files_seen += 1
                        heapq.heappush(largest, (size, entry.path))
                        if len(largest) > top_files:
                            heapq.heappop(largest)
                        if size >= min_size:
                            if candidate_count >= max_candidates:
                                truncated = True
                                break
                            candidates.setdefault(size, []).append(
                                (entry.path, info.st_dev, info.st_ino)
                            )
                            candidate_count += 1
                    except OSError:
                        errors += 1
                    if progress and files_seen % 100 == 0:
                        progress(files_seen, "indexing")
                if truncated:
                    break
        except OSError:
            errors += 1
        if truncated:
            break

    hash_cache: dict[tuple[int, int, int], str] = {}
    duplicate_buckets: dict[tuple[int, str], list[tuple[str, int, int]]] = {}
    files_hashed = 0
    if not truncated:
        for size, paths in candidates.items():
            if len(paths) < 2:
                continue
            for path, device, inode in paths:
                if cancelled() or time.monotonic() - started >= max_seconds:
                    truncated = True
                    break
                identity = (device, inode, size)
                digest = hash_cache.get(identity)
                if digest is None:
                    try:
                        before = os.stat(path, follow_symlinks=False)
                        hasher = hashlib.sha256()
                        with open(path, "rb") as stream:
                            while True:
                                if cancelled() or time.monotonic() - started >= max_seconds:
                                    truncated = True
                                    break
                                block = stream.read(1024 * 1024)
                                if not block:
                                    break
                                hasher.update(block)
                        if truncated:
                            break
                        after = os.stat(path, follow_symlinks=False)
                        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                            errors += 1
                            continue
                        digest = hasher.hexdigest()
                        hash_cache[identity] = digest
                        files_hashed += 1
                    except OSError:
                        errors += 1
                        continue
                duplicate_buckets.setdefault((size, digest), []).append((path, device, inode))
                if progress and files_hashed and files_hashed % 10 == 0:
                    progress(files_hashed, "hashing")
            if truncated:
                break

    groups = []
    for (size, digest), matches in duplicate_buckets.items():
        identities = {(device, inode) for _, device, inode in matches}
        if len(identities) < 2:
            continue
        groups.append({
            "sha256": digest,
            "bytes_each": size,
            "paths": sorted(path for path, _, _ in matches),
            "reclaimable_bytes": size * max(0, len(identities) - 1),
        })
    groups.sort(key=lambda group: group["reclaimable_bytes"], reverse=True)

    return {
        "root": str(root),
        "files_seen": files_seen,
        "files_hashed": files_hashed,
        "errors": errors,
        "truncated": truncated,
        "duplicates": groups,
        "duplicate_groups": len(groups),
        "reclaimable_bytes": sum(group["reclaimable_bytes"] for group in groups),
        "largest_files": [{"path": path, "bytes": size}
                          for size, path in sorted(largest, reverse=True)],
    }
