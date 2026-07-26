"""
Save/load a trained ML model to disk, so live trading can use a model that
was trained *once*, periodically (e.g. weekly, via
train_stock_model.py + a GitHub Actions retrain job), instead of fitting a
brand-new model from scratch on every single live decision and immediately
throwing it away. This is what makes the model's "opinion" actually persist
between live runs rather than resetting every 5 minutes / every day.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# json for reading/writing the small metadata sidecar file (threshold and
# whatever else the caller wants remembered alongside the model itself).
import json
# Path gives cross-platform file path handling (mkdir, suffix, exists, etc.)
# instead of manually gluing strings together.
from pathlib import Path

# joblib is the standard way to serialize scikit-learn models to disk -
# handles numpy arrays inside the model more efficiently than plain pickle.
import joblib


def _meta_path(path: Path) -> Path:
    # Given the model file's path (e.g. "model.joblib"), derive the path
    # of its metadata sidecar file by appending ".meta.json" onto the
    # existing suffix (e.g. "model.joblib.meta.json") - keeps the two
    # files sitting next to each other and obviously paired by name.
    return path.with_suffix(path.suffix + ".meta.json")


def save_model(model, threshold: float, meta: dict, path: str) -> None:
    # Normalize the incoming string into a Path object so the rest of the
    # function can use Path's methods.
    path = Path(path)
    # Create any missing parent directories (e.g. a "models/" folder that
    # doesn't exist yet); exist_ok=True means don't error if it's already there.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write the actual trained model object to disk.
    joblib.dump(model, path)
    # Write the metadata sidecar as JSON: everything in the caller's meta
    # dict, plus the calibrated threshold merged in under its own key -
    # {**meta, "threshold": threshold} builds a new dict containing both.
    _meta_path(path).write_text(json.dumps({**meta, "threshold": threshold}, indent=2))


def load_model(path: str):
    """Returns (model, threshold, meta), or None if no saved model exists yet."""
    path = Path(path)
    meta_path = _meta_path(path)
    # Both the model file and its metadata sidecar need to exist - if
    # either is missing, there's no valid saved model to load, so report
    # "nothing here" instead of crashing on a half-present file pair.
    if not path.exists() or not meta_path.exists():
        return None
    model = joblib.load(path)
    meta = json.loads(meta_path.read_text())
    # Pull threshold back out of the metadata dict as its own return
    # value (mirroring how save_model merged it in), alongside the full
    # meta dict in case the caller wants the other fields too.
    return model, meta["threshold"], meta
