# Techgraph

**Mismatches, Modules and Entrenchment: a theory and simulation testbed of technological change.**

Techgraph represents needs and resources as substances, and technologies as performing three functions on them: processing, transport and storage. Institutions shape which responses are possible and who pays for them. The research program develops a general theory and reusable experimental testbed, with applied cases used to examine mechanisms and validate the framework.

Author: Mamadou Seck, PhD.

## Current checkpoint — 4 October 2026

The `main` branch contains the version 4 source tree, documentation, tests, selected benchmark results, and two applied cases. Start with [HANDOFF.md](HANDOFF.md) for the current state, verification history, limitations, and next steps.

The current framework includes generic policy primitives, spatial atoms and overlapping partitions, demands and resources with generic substances, representative operating periods, and rolling-horizon operation with initial storage, terminal storage values, and committed activities.

| Area | Entry point | Status |
| --- | --- | --- |
| Model package | [techgraph/](techgraph/) | Core model and opt-in mechanisms. |
| Space and policy | [Design and implementation status](TECHGRAPH_SPACE_AND_POLICY_DESIGN.md) | Generic spatial layer and policy primitives. |
| Institutions, periods, and demand | [Institutions](INSTITUTIONS.md), [representative days](REPRESENTATIVE_DAYS.md), [demands](DEMANDS.md) | Documentation of the v4 extensions. |
| Verification | [tests/](tests/), [genx_bench/](genx_bench/) | Tests, GenX benchmark inputs, scripts, and selected reference outputs. |
| Virginia power | [Case README](cases/virginia_dc/README.md) | Version 9 under the case assumptions; version 10 using the Energy Plan assumptions described in the handoff. Publication is paused. |
| Potomac water | [Case README](cases/potomac_water/README.md) | Standalone simulator, Techgraph implementation, flow data, study-result tables, and discussion draft. Convergence and horizon analysis remain in progress. |
| Earlier v4 mechanisms | [README_V4.md](README_V4.md), [START_HERE_V4.md](START_HERE_V4.md) | Earlier mechanism notes and campaign roadmap; use the October 4 handoff for current status. |

## Run the current source

Use a Python environment with the dependencies recorded in [requirements-demand-sweep.txt](requirements-demand-sweep.txt). From the repository root:

```bash
python3 -m pip install -r requirements-demand-sweep.txt
export TECHGRAPH_BACKEND=scipy
cd cases/virginia_dc
python3 check_reference.py
```

The Virginia reference check compares two case runs with stored results. It was rerun for this repository update on 4 October 2026 and returned `PASS`, with zero relative difference for both `v10_DF` and `v9_CPflex`. All 142 Python files in the supplied source snapshot also passed a syntax parse.

The handoff records 725 passing tests, three pre-existing failures in `tests/test_network_worlds.py`, and three excluded test modules. That full suite was not rerun for this source import. Its recorded command, from the repository root, is:

```bash
TECHGRAPH_BACKEND=scipy python3 -m pytest -q tests --ignore=tests/test_discovery.py --ignore=tests/test_measurement_spine.py --ignore=tests/test_stateful_replay.py
```

## Resume the water work

The next step is a controlled comparison of the Techgraph and standalone water models across nine Historic demand scenarios and the two selected drought windows. Match the operating rules, available information, and Jennings Randolph storage priorities before interpreting residual differences. Then complete the horizon scan and update the discussion draft, as described in [HANDOFF.md](HANDOFF.md).

The saved [water scan](cases/potomac_water/results/tg_scan.json) is partial: it contains 28 of the planned 90 variant-by-drought runs, covering the three 2030 demand scenarios. The supplied scan script retains the earlier rule-matched configuration. Its results therefore remain a checkpoint for further work. Agreement between the two implementations and agreement with ICPRB's published study are separate validation questions.

## Earlier complete research backup

The [29 September 2026 release](https://github.com/dioufseck-rgb/techgraph/releases/tag/backup-2026-09-29) preserves the earlier complete research archive. Download [Techgraph_Complete.zip](https://github.com/dioufseck-rgb/techgraph/releases/download/backup-2026-09-29/Techgraph_Complete.zip) for the approximately 779 MB backup containing full saved checkpoints, raw histories, earlier source packages, paper drafts, figures, theory notes, research cases, and provenance records.

That archive records the earlier principal campaigns: 910 accepted histories and 63,232 periods across 56 world ancestries. Raw retries and earlier campaigns are retained there and must not be counted as additional independent observations. After extracting it, read `Techgraph_Complete/START_HERE.md` and keep its checkpoint versions in separate directories.

**Code → Download ZIP** now downloads the current committed source checkpoint. The release attachment provides the large historical archive. Both remain available.

## Data and reproducibility scope

The current source includes the two USGS flow series used by the water case, parsed water-study scenario tables, Virginia representative days, and selected reference results. Full campaign traces, regenerated `runs*.json` outputs, raw Dominion hourly load, the external GenX/Julia environment, and the source report PDFs are outside this source snapshot; see the handoff and case READMEs for details. Some historical helper scripts retain paths to their original execution environment.

This is an evolving research checkpoint. The handoff distinguishes verified implementation behavior, provisional case results, and work still to be completed.
