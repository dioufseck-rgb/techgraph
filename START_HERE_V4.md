# Techgraph v4 handoff

This bundle contains the v4 source tree, which is the frozen demand-sweep v3 code plus opt-in realism mechanisms, together with the completed diagnostic results and the reports from the 30 September 2026 session.

Read these first:
- `README_V4.md`: the mechanisms, how to switch them on, and how they are verified.
- `Techgraph_Model_Review_Realism.md`: the review that motivated v4. One claim in it was later corrected (see the next file).
- `Techgraph_v4_Run_Analysis.md`: results of the oracle-forecast and relocation-fix replays.
- `Techgraph_Water_World_and_Benchmark_Spec.md`: the planned water world and the GenX benchmark.

Two corrections to the review:
- The unused-ancestry count is below the uniform-parent null (39 observed, 57.5 expected), so it is not a null artifact.
- Storage stays idle even under oracle forecasts, so the static forecast is not the main reason for idle storage.

`results_v4/` holds the run logs and summaries. The full traces are not included because of their size. The archived v3 data used for comparison come from the original release bundle (`Techgraph_Complete.zip`, release backup-2026-09-29).

Pending work, all resumable: run `run_v4.py specs_d1.json results/d1` (13 oracle worlds remain, plus all AR(1) runs) and `specs_d2.json` (the switching-cost replay); one infrastructure-lump smoke run; 21 remaining relocation reruns (`reloc_check.py`); then the GenX benchmark.

Defaults reproduce v3 exactly. Run `pytest tests/test_v4_realism.py` to confirm.
