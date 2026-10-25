# DPN TECHNOLOGY // SYSTEM OPTIMIZER v2.0

[![DPN Green Gates](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/green-gates.yml/badge.svg)](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/green-gates.yml) [![DPN CodeQL Security](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/codeql.yml/badge.svg)](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/codeql.yml) [![DPN Windows Package](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/package-windows.yml/badge.svg)](https://github.com/DPN-Technology/DPN-System-Optimizer/actions/workflows/package-windows.yml)


**Windows 10/11 · Python 3.10+ · Free · No telemetry · Conservative by default**

System Optimizer is a local-first Windows maintenance tool with a red-and-black desktop GUI and a scriptable CLI. It is not a registry cleaner, RAM booster, driver updater, antivirus replacement, or a promise to speed up a CPU by deleting files.

## Quick start

1. Download and **extract** this ZIP to a permanent location, e.g. `C:\DPN-Tools\System-Optimizer\`. **Do not run directly from inside the ZIP.**
2. Install Python 3.10+ from <https://www.python.org/downloads/windows/> if you do not already have it. During setup, choose **Add python.exe to PATH** or install the `py` launcher.
3. Double-click **`START_DPN_OPTIMIZER.bat`** to open the desktop app.
4. For full CPU, RAM and process monitoring, double-click **`INSTALL_MONITORING.bat`** to install free `psutil`. The cleaner, reports, inventory and scheduler work without it. Restart the app afterward.
5. Choose **Cleaner → Scan / Preview** first; then **Apply Cleanup** only if you approve the deletion targets. The app confirms before deleting.

## Main features

| Module | Implemented behavior |
| --- | --- |
| DPN desktop interface | Branded black-and-red control center with an animated binary boot console, a live status header, numbered module navigation, and responsive centered window sizing. The startup progress is an intro animation, not a timed hardware diagnostic. |
| Performance dashboard | Sampled CPU usage with psutil, RAM, disk, top processes by RAM, guidance, two-minute sparklines, and a snapshot headroom score. Updates every 5 seconds while GUI is open. The score averages available CPU, RAM, and disk headroom; it is not a diagnosis or long-term health rating. |
| Process Explorer | Optional psutil-backed local process snapshot with CPU, RAM, owner, executable path, and status, plus filtering. Ending a process is a separate, explicit confirmation; only processes verified as belonging to the current user and outside protected Windows locations are eligible. Windows termination is immediate, so unsaved work may be lost. |
| User temp cleaner | Ages files before eligibility (default 48 hours); skips recently changed files, symlinks/junctions, inaccessible/locked files. |
| Optional cache cleanup | DirectX shader cache; explicitly selected Windows Error Reporting files and user crash dumps; Chrome/Edge *cache files only* if all browsers are closed. |
| Windows temp | Explicitly selected; may require admin. Never on by default. |
| Disk Space Map | Read-only scan of your user profile, Downloads, Documents, or system drive that ranks the largest folders with bar charts and lists the 25 largest files, with an *Open Folder* button. Symlinks/junctions are never followed, the scan can be stopped, and system-drive scans stop after 45 seconds (results are then marked partial). It never deletes or changes anything. |
| Duplicate & Large File Finder | Read-only SHA-256 duplicate matching and largest-file ranking across the selected profile, Documents, Downloads, or system drive. Same-size candidates only are hashed; the minimum size defaults to 1 MB. Scan is cancellable and bounded to 90 seconds or 50,000 candidates. Reparse points are skipped, changed/unreadable files are not trusted, and hard links are not counted as recoverable space. Potential savings are estimates; no files are deleted or modified. |
| Startup analyzer | Read-only inventory of Run/RunOnce values and Startup-folder files, including machine-wide keys when accessible. Recognizable sync, chat, and launcher apps are flagged as potentially high impact using a cautious name-based heuristic; it does not measure boot time or verify publisher signatures, so publisher status is shown as unknown. |
| Windows health | Manually triggered `sfc /verifyonly` or `DISM /Online /Cleanup-Image /ScanHealth`, no automatic repair. |
| Scheduler | Opt-in task using Windows Task Scheduler. Daily **user temp only**, 48+ hours old, limited privileges; you specify its local time. |
| Local reports | A JSON file per preview/cleanup showing category counts and deleted bytes; no individual scanned filenames or content. |

### Important safety notes

- Preview-only is the default. **Deletion is permanent after you explicitly approve it.** It does not use the Recycle Bin.
- The Process Explorer never ends processes automatically. Its explicit end action can immediately close an application and lose unsaved work; protected Windows processes, unverified identities, and processes owned by other users are denied.
- The only default cleanup category is user temp. Other categories must be opted into.
- Disk Map and File Finder are read-only. Duplicate matching hashes file contents locally; filenames and file contents are not uploaded or saved in reports. Potentially recoverable duplicate space is an estimate and does not imply that removing any copy is safe.
- The tool does **not** clean Desktop, Documents, Downloads, pictures, browser cookies/passwords/history, registry settings, Windows Prefetch, or installed programs.
- Reparse points / symlink files and folders are skipped; the approved cleanup root is never removed. Only empty child directories are removed.
- Age check: 48+ hours by default, but app caches/crash reports might still be useful. Close work applications and use preview before cleanup.
- Deleting shader caches may temporarily increase load times while rebuilt; crash reports can be valuable for troubleshooting. Neither is selected by default.
- Browser cache cleanup is skipped if Chrome or Edge are running or process state cannot be verified.
- System temp cleanup may return access-denied errors. **Do not force close applications or change system permissions to delete locked files.**
- Scheduled jobs will fail if you move or delete this script; disable and re-enable the job after relocating it. Scheduled tasks may require you to be signed in and your PC powered on.
- Diagnostic measurements and cleaned file sizes are *not* proof of speed improvement. Free space change can differ from summed file sizes due to compression, concurrent activity, and filesystem accounting.
- If your device is managed by an employer, follow their IT policies before scheduling or cleaning system files.

## Command line examples

In PowerShell, open the extracted folder and run:

```powershell
py -3 dpn_system_optimizer.py --help
py -3 dpn_system_optimizer.py diagnose
py -3 dpn_system_optimizer.py diagnose --json  # machine-readable output for automation
py -3 dpn_system_optimizer.py startup
py -3 dpn_system_optimizer.py preview
py -3 dpn_system_optimizer.py preview --categories user_temp shader_cache --age-hours 72
py -3 dpn_system_optimizer.py clean --categories user_temp --age-hours 48 --apply
py -3 dpn_system_optimizer.py clean --categories user_temp browser_cache --apply
py -3 dpn_system_optimizer.py history
py -3 dpn_system_optimizer.py schedule status
py -3 dpn_system_optimizer.py schedule install --time 09:00
py -3 dpn_system_optimizer.py schedule remove
py -3 dpn_system_optimizer.py health sfc-verify
py -3 dpn_system_optimizer.py health dism-scan
```

**Warning:** `clean` *without* `--apply` is a preview and deletes nothing. Browser caches are skipped when either Chrome or Edge are active.

## Reports and privacy

Reports are stored at:

`%LOCALAPPDATA%\DPN Technology\System Optimizer\Reports\`

No network/API calls are made by the application. Optional psutil installation uses pip to download psutil, if you choose it. Reports are local and include category names, totals, timestamps, and counts — **not filenames, file contents, passwords, or browser history**. Startup inventory can display command lines that contain personal paths; it is not uploaded.

## Troubleshooting

- **Windows opens a console instead of the GUI:** install Python from python.org with Tkinter support; launch with `START_DPN_OPTIMIZER.bat`.
- **CPU reads N/A:** install optional psutil (`INSTALL_MONITORING.bat`) and restart.
- **No eligible files:** files may be recent, folders absent, or not among approved cleanup roots. A preview report states the number of roots scanned.
- **Some files remain:** expected for files in use, protected folders, or files newer than the cutoff.
- **SFC/DISM access denied:** run a standalone elevated Windows Terminal session with proper authorization, or use Windows' built-in tools manually. The app does not elevate itself.
- **Windows task failed:** use `schedule status` and Task Scheduler to inspect the task. Reinstall if Python/script path changed.
- **No noticeable speedup:** inspect startup items, high memory/CPU processes, disk health, and hardware limitations. Removing temp files primarily frees disk space.

## Development

Standard-library cleaner, optional `psutil`, no third-party GUI framework.

```shell
python -m unittest discover -s tests -v
python -m compileall -q .
```

### Security model and limitations

Approved cleanup roots are enumerated by code; the user cannot supply an arbitrary path. Every root and subdirectory is inspected for symlinks and Windows reparse-point flags. Entries are re-checked before deletion. Path and file operations inherently have a small time-of-check/time-of-use race if a privileged local process actively changes folders concurrently; avoid running on untrusted or compromised systems.

### Files

- `dpn_system_optimizer.py` — main executable script
- `dpn_optimizer/cleaner.py` — conservative cleanup engine + JSON reports
- `dpn_optimizer/diagnostics.py` — performance snapshots
- `dpn_optimizer/startup.py` — startup inventory
- `dpn_optimizer/scheduler.py` — optional Task Scheduler integration
- `dpn_optimizer/health.py` — read-only Windows system verification
- `dpn_optimizer/diskmap.py` — read-only disk space analysis
- `dpn_optimizer/assets/` — DPN logo (sourced from the DPN-Technology GitHub organization avatar) in sizes used by the window icon, sidebar and splash
- `dpn_optimizer/gui.py` — Tkinter desktop interface
- `dpn_optimizer/cli.py` — commands
- `START_DPN_OPTIMIZER.bat` — GUI launcher
- `INSTALL_MONITORING.bat` — optional free monitoring dependency installer
- `tests/test_optimizer.py` — regression tests

© 2026 DPN Technology. Internal utility; no third-party proprietary dependencies bundled.

## Engineering and CI security

This repository contains the full Python source, conservative deletion safeguards, and GitHub Actions. **Pull requests** run Ruff correctness checks, 6 Linux/Windows Python test configurations, Bandit security scanning, `pip-audit` checks of runtime and developer dependencies, CodeQL Python security analysis, and GitHub dependency review. The **Required policy gate** job turns red if any underlying required CI job does not succeed.

On pushes to `main` and tagged builds, the Windows packaging workflow produces a ZIP plus SHA-256 checksum available under the workflow run's **Artifacts** section. The build is source-only, no unsigned bundled `.exe`. Dependabot checks GitHub Actions and Python dependencies weekly.

**Important:** Workflow gates are not the same as branch protection. An organization administrator should require the green CI and security checks and human review using repository rulesets. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

This project is proprietary DPN Technology software. See [LICENSE.txt](LICENSE.txt). Public visibility does not grant a license to redistribute, sell, or use it.
