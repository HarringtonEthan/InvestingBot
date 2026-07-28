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

# hashlib for the model file's integrity hash - see load_model()'s
# docstring for why this matters.
import hashlib
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


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    # dict, plus the calibrated threshold and this file's own hash merged
    # in under their own keys - the hash is what load_model() checks
    # against before trusting this file later.
    _meta_path(path).write_text(json.dumps(
        {**meta, "threshold": threshold, "model_sha256": _file_sha256(path)}, indent=2
    ))


def load_model(path: str):
    """
    Returns (model, threshold, meta), or None if no saved model exists yet.

    Raises ValueError if the model file's contents don't match the hash
    recorded in its own metadata sidecar at save time. joblib's own docs
    warn that loading a persisted object can execute arbitrary code, and
    this file is written by an automated retrain workflow, then trusted
    unconditionally by live trading code later - a hash mismatch means
    the file changed some other way since save_model() last wrote it
    (tampering, a bad merge, disk corruption), which is exactly the case
    this check exists to catch before joblib.load() ever runs on it.
    Models saved before this check existed (no "model_sha256" in their
    metadata) load as before, with a warning, since there's nothing on
    record yet to verify against.
    """
    path = Path(path)
    meta_path = _meta_path(path)
    # Both the model file and its metadata sidecar need to exist - if
    # either is missing, there's no valid saved model to load, so report
    # "nothing here" instead of crashing on a half-present file pair.
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    expected_hash = meta.get("model_sha256")
    if expected_hash is None:
        print(f"WARNING: {meta_path} has no recorded model hash (saved before this "
              f"integrity check existed) - loading {path} without verification.")
    else:
        actual_hash = _file_sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Refusing to load {path}: its contents don't match the hash recorded "
                f"in {meta_path} when it was last saved (expected {expected_hash[:12]}..., "
                f"got {actual_hash[:12]}...). Re-run train_stock_model.py to produce a "
                f"trustworthy model instead of loading this one."
            )
    model = joblib.load(path)
    # Pull threshold back out of the metadata dict as its own return
    # value (mirroring how save_model merged it in), alongside the full
    # meta dict in case the caller wants the other fields too.
    return model, meta["threshold"], meta
