# Parameter sweeps

Every grid search `optimize.py` has ever run, real market data, all
committed as evidence (see the main [README](../../README.md)'s
"Current live status" and `docs/RESEARCH.md` for how these get used).

## Which files back the ACTIVE live config

- **Crypto** (`day_trading`, dip=-4.0% / profit=+1.0% / stop=-5.0%):
  - `param_sweep.csv` - the 90-combo grid search that found this combo
  - `param_sweep_overview.png` - same search, chosen combo circled

- **Stocks** (`rule_based`, 5-minute bars, dip=-1.5% / exit=2.0% - the
  best of 8 candidates walk-forward tested, see
  `../walk_forward/README.md`):
  - `param_sweep_overview_stocks_5m_all.png` - the 5-minute grid search
    this candidate came from, its point circled

## Everything else here

Every other file (`param_sweep_stocks.csv`, `param_sweep_stocks_5m*.csv`,
`param_sweep_overview_stocks.png`, `param_sweep_overview_stocks_daily_all.png`,
etc.) is a **candidate that was explored, not deployed** - part of the
search that led to the active config above, not itself currently
running. See `docs/RESEARCH.md` for the full candidate-by-candidate
breakdown.
