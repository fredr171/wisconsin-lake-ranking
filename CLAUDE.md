# Working rules for this project

- After any change to `config.py`, `lake_finder.py`, `scoring.py` or
  `build_listing_report.py`, re-run the pipeline (`python lake_finder.py`, then
  `python build_listing_report.py`) and `pytest`, and update `README.md` and
  `docs/` in the same change, so the docs describe what the code does now.
- Record notable findings (a bug fix, a data-quality catch, a new data source)
  in `docs/validation.md`.
- `data/` holds caches only. Never hand-edit them; fix the code that writes them.
- A failed lookup must never be written to a cache. It's reported, and it's
  retried on the next run.
- Before changing a score because a reviewer (human or AI) suggested it, check
  the claim against the data and record the result in `docs/validation.md`.
