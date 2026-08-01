"""
Save/load a trained ML model to disk, so a model can be trained once and
reused across many runs instead of retraining from scratch every time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib


def _meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_model(model, threshold: float, meta: dict, path: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    _meta_path(path).write_text(json.dumps(
        {**meta, "threshold": threshold, "model_sha256": _file_sha256(path)}, indent=2
    ))


def load_model(path: str):
    """
    Returns (model, threshold, meta), or None if no saved model exists yet.

    Raises ValueError if the model file's contents don't match the hash
    recorded in its own metadata sidecar at save time - catches tampering,
    a bad merge, or disk corruption before joblib.load() runs on an
    untrustworthy file. Models saved before this check existed (no
    "model_sha256" in their metadata) load as before, with a warning.
    """
    path = Path(path)
    meta_path = _meta_path(path)
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
                f"got {actual_hash[:12]}...). Re-train to produce a trustworthy model instead "
                f"of loading this one."
            )
    model = joblib.load(path)
    return model, meta["threshold"], meta
