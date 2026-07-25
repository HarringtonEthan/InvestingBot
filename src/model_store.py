"""
Save/load a trained ML model to disk, so live trading can use a model that
was trained *once*, periodically (e.g. weekly, via
train_stock_model.py + a GitHub Actions retrain job), instead of fitting a
brand-new model from scratch on every single live decision and immediately
throwing it away. This is what makes the model's "opinion" actually persist
between live runs rather than resetting every 5 minutes / every day.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib


def _meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def save_model(model, threshold: float, meta: dict, path: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    _meta_path(path).write_text(json.dumps({**meta, "threshold": threshold}, indent=2))


def load_model(path: str):
    """Returns (model, threshold, meta), or None if no saved model exists yet."""
    path = Path(path)
    meta_path = _meta_path(path)
    if not path.exists() or not meta_path.exists():
        return None
    model = joblib.load(path)
    meta = json.loads(meta_path.read_text())
    return model, meta["threshold"], meta
