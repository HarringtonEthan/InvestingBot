"""
ML "dip filter": predicts, on days that look like a dip, whether the price
is likely to bounce - defined as being at least `bounce_pct` higher within
the next `horizon` trading days.

This is a filter layered on top of the rule-based strategy, not a
standalone predictor: it's only ever queried on days the rule-based
strategy already flagged as a dip.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from .features import FEATURE_COLUMNS


def build_labels(df: pd.DataFrame, horizon: int = 10, bounce_pct: float = 0.03) -> pd.Series:
    close = df["Close"]
    future_max = close.shift(-1).rolling(horizon).max().shift(-(horizon - 1))
    # future_max[i] = max close over (i+1 .. i+horizon)
    bounced = (future_max / close - 1.0) >= bounce_pct
    return bounced.astype(float)


def _labeled_features(df: pd.DataFrame, horizon: int, bounce_pct: float):
    labels = build_labels(df, horizon=horizon, bounce_pct=bounce_pct)
    feats = df[FEATURE_COLUMNS]
    valid = ~feats.isna().any(axis=1) & ~labels.isna()
    return feats[valid], labels[valid]


def _fit(X: pd.DataFrame, y: pd.Series):
    if y.nunique() < 2:
        raise ValueError("training labels have only one class; widen the date range")

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=4,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=42,
    )
    model.fit(X, y)

    train_scores = model.predict_proba(X)[:, 1]
    threshold = float(np.percentile(train_scores, 75))
    return model, threshold, train_scores


def train_model(train_df: pd.DataFrame, horizon: int = 10, bounce_pct: float = 0.03):
    """
    Returns (model, calibrated_threshold, train_scores).

    The threshold is picked as the 75th percentile of the model's predicted
    probabilities on the *training* set (never on test data) - i.e. "only
    act on the dips the model is most confident about, relative to what it
    saw in training." This avoids hardcoding an absolute cutoff that may
    sit entirely outside the model's achievable score range.
    """
    X, y = _labeled_features(train_df, horizon, bounce_pct)
    return _fit(X, y)


def train_model_multi(train_dfs: dict[str, pd.DataFrame], horizon: int = 10, bounce_pct: float = 0.03):
    """
    Same as train_model, but pools labeled rows from several tickers into
    one training set before fitting a single model, instead of overfitting
    to one ticker's idiosyncrasies. Rolling-window features/labels are
    computed per ticker first (never across a ticker boundary) - only the
    resulting already-computed rows are pooled together.

    Returns (model, calibrated_threshold, train_scores).
    """
    X_parts, y_parts = [], []
    for df in train_dfs.values():
        X, y = _labeled_features(df, horizon, bounce_pct)
        if len(X):
            X_parts.append(X)
            y_parts.append(y)

    if not X_parts:
        raise ValueError("no usable training rows across any ticker")

    X = pd.concat(X_parts, ignore_index=True)
    y = pd.concat(y_parts, ignore_index=True)
    return _fit(X, y)
