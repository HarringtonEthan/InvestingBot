# Walk-forward validation

Every `walk_forward.py` run - fixed parameters evaluated across several
sequential, non-overlapping real-data windows - all committed as
evidence (see the main [README](../../README.md)'s "Current live
status" and `docs/RESEARCH.md` for how these get used).

## Which files back the ACTIVE live config

- **Crypto** (`day_trading`, dip=-4.0% / profit=+1.0% / stop=-5.0%):
  `walk_forward.csv` + `walk_forward_winner.png` - `walk_forward.py`'s
  own default parameters are this exact live config, so these are its
  direct validation.

- **Stocks** (`rule_based`, 5-minute bars, dip=-1.5% / exit=2.0% - the
  best of 8 candidates walk-forward tested):
  `walk_forward_stocks_5m_best.csv` + `walk_forward_stocks_5m_best_candidate.png`
  (this candidate's own per-ticker data/chart), plus
  `walk_forward_stocks_summary.csv` + `walk_forward_stocks_summary.png`
  (the comparison across all 8 candidates, this one highlighted).

## Everything else here

`walk_forward_stocks.csv` (the 3 daily `rule_based` candidates),
`walk_forward_stocks_candidate.png` (one specific daily candidate's
chart), and `walk_forward_stocks_ml_filtered.csv` are all **candidates
that were tested, not deployed** - part of the 8-candidate search that
led to the active stock config above, not currently running. See
`docs/RESEARCH.md` for the full candidate-by-candidate breakdown.
