# Weighted representative days in Techgraph

## What changed

`Scenario` has two optional fields:

- `period_weights`: one positive weight per period. It multiplies that period's operating cost and emissions. The usual choice is the number of days that the period's representative day stands for, with `days=365`, so the objective is annual.
- `cycle_length`: the number of periods in one representative day. Storage then cycles within each day instead of across the whole horizon.

Hourly balances, capacity limits and storage dynamics are unchanged. Prices returned by `model.solve(fixed=True)` are divided by the period weight, so they remain in $/MWh. The institutions module weights energy quantities by the same weights. With neither field set, every equation is identical to v4.

Files changed: `catalog.py` (fields), `operation.py` (weighted costs and emissions, storage successor), `dynamic.py` and `model.py` (weighted fuel and unmet-demand costs; price scaling), `institutions.py` (weighted energy), `flow_audit.py` (storage successor). Weights are supported for legacy designs without a daily hub requirement; other configurations raise an error.

## Verification

The formulation was checked against GenX's multi-day mode (`genx_bench/make_multiday_case.py`, `genx_bench/multiday_techgraph.py`). Two cases were built from the GenX New England example with unequal day weights summing to 8,760 hours:

| Case | GenX objective | Techgraph objective | Relative difference |
|:--|--:|--:|--:|
| Four days (2,000, 2,500, 2,260 and 2,000 hours) | $4,669,827,340 | $4,669,827,340 | 2 × 10⁻¹⁶ |
| Two days (5,000 and 3,760 hours) | $5,011,866,098 | $5,011,866,098 | 2 × 10⁻¹⁵ |

All capacities agree. The full test suite gives 691 passed and 3 failed; the same 3 tests fail on the unmodified v4 code, and 3 further test modules import helper scripts that are not in the handoff archive.

## Caution

A peak day with a small weight makes shortages in its hours cheap. Reliability should therefore be enforced with explicit adequacy and deliverability requirements (see `INSTITUTIONS.md`), not left to the cost of unserved energy.

## Blocks of different lengths

`Scenario.cycle_blocks` lists `(start, length)` blocks that tile the horizon. Storage cycles within each block, and flexible load shifts balance within each block. This allows typical 24-hour days alongside a chronological multi-day period, such as a three-day cold snap in which long-duration storage can carry energy from one day to the next. With one-day cycling, storage of more than 24 hours cannot be represented physically. `tests/test_institutions.py::test_cycle_blocks_let_storage_cross_days` checks the difference.

## Time-varying variable costs

`Design.var_cost_profile` names a profile in `Scenario.profiles`; the design's variable cost is multiplied by that profile period by period. It is used to price imports at an hourly market price. A flat import price had made existing plants run unrealistically hard and imports near zero, which only a comparison with observed generation revealed.

## Lesson

Agreement with GenX shows that the equations are implemented correctly. It does not show that a configuration matches reality. Every case study should include a baseline electricity balance (generation by source, imports, storage flows and capacity factors) compared with observed data on a stated scope, before projections are interpreted.
