# Contributing to DPN System Optimizer

## Local development

Python 3.10+ is required. The Windows GUI uses the standard-library Tkinter module. Optional monitoring uses `psutil`.

```shell
python -m unittest discover -s tests -v
python -m compileall -q dpn_optimizer tests dpn_system_optimizer.py
python -m pip install -r requirements-dev.txt
ruff check .
bandit -r dpn_optimizer dpn_system_optimizer.py -ll -q -s B404,B603,B607
pip-audit --strict -r requirements.txt
pip-audit --strict -r requirements-dev.txt
```

## GitHub review and green gate policy

1. Work on a feature branch and open a PR against `main`.
2. The **DPN Green Gates / Required policy gate** job requires lint, six OS/Python test combinations, and dependency+source audits.
3. The separate **DPN CodeQL Security** and **DPN Dependency Review** workflows provide additional security signals.
4. Use repository branch rules to block merges until **Required policy gate**, **CodeQL Python security analysis**, and **Dependency review (high/critical blocked)** complete successfully and approvals are granted. These repository settings must be enabled by an administrator; workflow YAML alone does not enforce branch protection.
5. Treat red gates as defects. Fix the code or update tests with a documented explanation—do not silently ignore failures.
6. Packaging on `main` or a version tag produces a Windows ZIP plus SHA-256 checksum as an Actions artifact, not an unsigned executable.

Do not commit personal cleanup reports, logs, private system information, tokens, or Python virtual environments.
