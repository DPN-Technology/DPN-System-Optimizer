# Security Policy — DPN System Optimizer

DPN System Optimizer is a Windows cleanup utility that can permanently delete files **only after approval**. Security issues involving unsafe cleanup boundaries, reparse points, privileges, report handling, or dependency supply chains are especially important.

## Supported versions

| Version | Security updates |
| --- | --- |
| 2.0.x | Supported |
| 1.x | Not supported |

## Reporting a vulnerability

Do **not** post exploit details, sensitive logs, personal file paths or proof-of-concept payloads in a public issue. Use the repository's **Security → Advisories → Report a vulnerability** option if private vulnerability reporting is enabled. If that option is not present, contact DPN Technology privately through its official channels. Never include credentials or unredacted personal information.

## Security engineering practices

- Read-only preview is default; deletion requires explicit UI confirmation or `clean --apply`.
- Fixed approved categories only; no arbitrary user path input; root folders are never unlinked.
- Reparse points and symlink files/directories are skipped, with checks repeated before deletion.
- Browser caches are skipped if browser process state cannot be confirmed or Chrome/Edge is running.
- Scheduled jobs are opt-in, restricted to aged user temp files, and use limited privileges.
- CI enforces Windows/Linux tests, Ruff correctness checks, Bandit, pip-audit, and CodeQL.
- GitHub-hosted scripts have least-privilege `permissions:` settings and pinned first-party actions where practicable.
- App reports remain local and exclude per-file names and contents.

**Limitations:** Filesystem race conditions cannot be fully eliminated by these safety checks; elevated or actively compromised systems are not supported threat models. File deletion is permanent, so review previews carefully.
