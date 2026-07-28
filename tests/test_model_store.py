"""
Tests for src/model_store.py's save/load round trip and its integrity
check: joblib.load() can execute arbitrary code for a maliciously
crafted or corrupted file (see joblib's own persistence docs), and this
model file is written by an automated retrain workflow, then trusted
unconditionally by live trading code later - load_model() should refuse
to load a file whose contents don't match the hash recorded in its own
metadata sidecar at save time.
"""

import json

import pytest

from src.model_store import load_model, save_model


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "model.pkl")
    save_model({"fake": "model"}, 0.6, {"tickers": ["SPY"]}, path)
    model, threshold, meta = load_model(path)
    assert model == {"fake": "model"}
    assert threshold == 0.6
    assert meta["tickers"] == ["SPY"]


def test_save_records_a_model_hash(tmp_path):
    path = tmp_path / "model.pkl"
    save_model({"fake": "model"}, 0.6, {}, str(path))
    meta = json.loads(path.with_suffix(".pkl.meta.json").read_text())
    assert "model_sha256" in meta
    assert len(meta["model_sha256"]) == 64  # sha256 hex digest length


def test_load_missing_model_returns_none(tmp_path):
    assert load_model(str(tmp_path / "does_not_exist.pkl")) is None


def test_load_rejects_a_model_file_that_no_longer_matches_its_hash(tmp_path):
    path = tmp_path / "model.pkl"
    save_model({"fake": "model"}, 0.6, {}, str(path))
    # Simulate the file changing some other way after save_model() wrote
    # it (tampering, a bad merge, disk corruption) - append a byte
    # without going through save_model again, so its hash no longer
    # matches what's recorded in the metadata sidecar.
    with path.open("ab") as f:
        f.write(b"\x00")
    with pytest.raises(ValueError, match="Refusing to load"):
        load_model(str(path))


def test_load_accepts_a_pre_hash_model_with_a_warning(tmp_path, capsys):
    # Models saved before this integrity check existed have no
    # "model_sha256" key in their metadata - load_model() should still
    # load them (there's nothing to verify against yet), just warn.
    path = tmp_path / "model.pkl"
    save_model({"fake": "model"}, 0.6, {}, str(path))
    meta_path = path.with_suffix(".pkl.meta.json")
    meta = json.loads(meta_path.read_text())
    del meta["model_sha256"]
    meta_path.write_text(json.dumps(meta))

    model, threshold, _ = load_model(str(path))
    assert model == {"fake": "model"}
    assert "WARNING" in capsys.readouterr().out
