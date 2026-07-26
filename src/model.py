"""
ML "dip filter": predicts, on days that look like a dip, whether the price
is likely to bounce - defined as being at least `bounce_pct` higher within
the next `horizon` trading days.

This is a filter layered on top of the rule-based strategy, not a
standalone predictor: it's only ever queried on days the rule-based
strategy already flagged as a dip.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# numpy for the percentile calculation used to calibrate the threshold;
# pandas for the DataFrame/Series types this module trains on.
import numpy as np
import pandas as pd
# The actual ML model type used - an ensemble of decision trees, a solid
# default choice for small/medium tabular data like this project's.
from sklearn.ensemble import RandomForestClassifier

# The exact list of feature columns to train/predict on - kept in one
# place (features.py) so training and prediction never drift apart.
from .features import FEATURE_COLUMNS


def build_labels(df: pd.DataFrame, horizon: int = 10, bounce_pct: float = 0.03) -> pd.Series:
    close = df["Close"]
    # shift(-1) looks one bar into the future (so today isn't counted as
    # part of its own "future"); rolling(horizon).max() then finds the
    # highest close over the following `horizon` bars; the second
    # shift(-(horizon - 1)) re-aligns that rolling window's result back
    # onto today's row instead of the last day of the window.
    future_max = close.shift(-1).rolling(horizon).max().shift(-(horizon - 1))
    # future_max[i] = max close over (i+1 .. i+horizon)
    # The label: did price ever get at least bounce_pct higher than
    # today's close within the lookahead window? True/False as a 0.0/1.0
    # float (astype(float) below) since that's what the classifier wants.
    bounced = (future_max / close - 1.0) >= bounce_pct
    return bounced.astype(float)


def _labeled_features(df: pd.DataFrame, horizon: int, bounce_pct: float):
    # Build the target labels for every row first.
    labels = build_labels(df, horizon=horizon, bounce_pct=bounce_pct)
    # Pull out just the feature columns the model is trained on.
    feats = df[FEATURE_COLUMNS]
    # Only keep rows where every feature is present AND the label itself
    # is defined - rows near the start (rolling windows not "warmed up"
    # yet) or the very end (not enough future bars left to know if it
    # bounced) get dropped here rather than fed to the model as garbage.
    valid = ~feats.isna().any(axis=1) & ~labels.isna()
    return feats[valid], labels[valid]


def _fit(X: pd.DataFrame, y: pd.Series):
    # nunique() counts distinct label values present; if every row is the
    # same class (e.g. every single dip bounced, or none did), there's
    # nothing for a classifier to learn to distinguish - fail loudly
    # rather than silently training a useless always-one-answer model.
    if y.nunique() < 2:
        raise ValueError("training labels have only one class; widen the date range")

    model = RandomForestClassifier(
        n_estimators=300,       # number of individual decision trees in the ensemble
        max_depth=4,            # cap each tree's depth - keeps individual trees simple to avoid overfitting
        min_samples_leaf=20,    # require at least 20 training rows per leaf, for the same reason
        class_weight="balanced",  # automatically up-weight whichever class (bounce/no-bounce) is rarer
        random_state=42,        # fixed seed - same training data always produces the same trained model
    )
    model.fit(X, y)

    # Score the model on its own training data, then pick a threshold as
    # the 75th percentile of those scores - see the train_model()
    # docstring below for why this is done on training data specifically.
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
    # Will collect each ticker's already-computed, already-filtered
    # feature/label rows before combining them into one training set.
    X_parts, y_parts = [], []
    for df in train_dfs.values():
        X, y = _labeled_features(df, horizon, bounce_pct)
        if len(X):
            # Only keep tickers that actually produced usable rows -
            # skip empty results rather than passing them to concat.
            X_parts.append(X)
            y_parts.append(y)

    if not X_parts:
        # Every ticker came back empty - nothing at all to train on.
        raise ValueError("no usable training rows across any ticker")

    # Stack every ticker's rows into one combined table/series;
    # ignore_index=True renumbers rows 0..N instead of keeping each
    # ticker's original (colliding) row numbers.
    X = pd.concat(X_parts, ignore_index=True)
    y = pd.concat(y_parts, ignore_index=True)
    return _fit(X, y)
