"""Validated, local-only appearance preferences."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile

from .cleaner import app_data_dir


@dataclass(frozen=True)
class AppearancePreferences:
    binary_rain: bool = True
    reduced_motion: bool = False
    show_intro: bool = True
    intensity: str = "Standard"

    def __post_init__(self) -> None:
        for name in ("binary_rain", "reduced_motion", "show_intro"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true or false.")
        if self.intensity not in ("Low", "Standard", "High"):
            raise ValueError("Intensity must be Low, Standard, or High.")


def preferences_path() -> Path:
    return app_data_dir() / "appearance.json"


def load_preferences(path: Path | None = None) -> AppearancePreferences:
    target = path if path is not None else preferences_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppearancePreferences()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Appearance preferences must be a JSON object.")
    known = asdict(AppearancePreferences())
    return AppearancePreferences(**{key: value for key, value in data.items() if key in known})


def save_preferences(preferences: AppearancePreferences, path: Path | None = None) -> None:
    """Replace atomically so a failed write cannot truncate existing preferences."""
    target = path if path is not None else preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(asdict(preferences), stream, indent=2)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
