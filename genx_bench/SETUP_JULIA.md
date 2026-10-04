# Julia and GenX setup used for the benchmark

- Julia 1.11.6 from julialang-s3.julialang.org.
- GenX 0.4.5, JuMP and HiGHS, installed into a project environment.
- The Julia package server was not reachable, so packages came from GitHub:
  `JULIA_PKG_SERVER="" julia -e 'using Pkg; Pkg.Registry.add(url="https://github.com/JuliaRegistries/General.git"); Pkg.activate("genx_env"); Pkg.add(["GenX","JuMP","HiGHS"])'`
- Set `GENX_PRECOMPILE=false`. The optional GenX precompile script ran out of memory on a 1-CPU, 3 GB machine.
- Example inputs come from the GenX repository at tag v0.4.5 (`example_systems/1_three_zones`), which matches the installed release.

Build one-day cases: `python make_genx_case.py 257` (run from a directory containing `genx_repo/`).
Run them: `julia run_genx_cases.jl`. Compare: `python stageA_techgraph.py <case_dir>` or `python stageA_all.py`.
