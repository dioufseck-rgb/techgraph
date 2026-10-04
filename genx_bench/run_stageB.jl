ENV["GENX_PRECOMPILE"]="false"
using Pkg; Pkg.activate(get(ENV,"GENX_ENV","genx_env")); using GenX
for d in split(get(ENV,"STAGEB_CASES","stageB_myopic,stageB_pf"),",")
    t=time()
    try run_genx_case!(joinpath(get(ENV,"STAGEB_DIR","stageB"),d)); println("DONE ",d," in ",round(time()-t),"s"); flush(stdout)
    catch e; println("FAIL ",d," ",sprint(showerror,e)); flush(stdout) end
end
println("ALL COMPLETE")
