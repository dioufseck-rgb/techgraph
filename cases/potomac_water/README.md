# Washington water supply, data centers and power

Run from this folder with `TECHGRAPH_BACKEND=scipy`.

## Data
- `data/usgs_01646502_adjusted_little_falls.txt`: USGS daily flow, Potomac (adjusted) near Washington, 1930-2025.
- `data/usgs_01638500_point_of_rocks.txt`: USGS daily flow, Potomac at Point of Rocks, 1929-2025.
- `data/wma_results.json`: the 36 scenario result tables (A.4-1 to A.4-36) parsed from ICPRB's 2025 WMA Water Supply
  Study. The study itself is not included; it is available from ICPRB.
- `data/wa_paths.json`: data-center power paths in Northern Virginia from the Virginia case (version 10).

## Models
- `prrism_lite.py`: a rule-following daily simulation after PRRISM, built from the study's published inputs. Inputs
  from the study are marked [study]; approximations are marked [approx]. Used as a cross-check.
- `tg_wma.py`: the same system in Techgraph, operated by rolling-horizon optimization. Each day: a plan over H days on
  forecast flows with Jennings Randolph releases in transit fixed, then a one-day realization on actual flows with the
  committed decisions fixed. Priorities are values on water left in storage, by zone. `Policy` options:
  `rule_offpotomac` (load shifts follow prrism_lite's rules), `same_info` (rules judged on actual next-day flow, Little
  Seneca same-day), `perfect` (plans see actual flows), `horizon`.
- `run_tg_scan.py`: nine historic-flow scenarios, 1930 and 1966 droughts, rule-matched and optimized variants, and a
  horizon scan. Writes `tg_scan.json`. The stored `results/tg_scan.json` is partial and predates the single-zone
  rule-matched variant (see HANDOFF.md).

## Draft
`draft/Potomac_DC_Power_Water_Draft.md`: the replication draft for discussion with ICPRB CO-OP (data-center water
demand, the historic-flow replication with sensitivity, and the cooling trade-off).
