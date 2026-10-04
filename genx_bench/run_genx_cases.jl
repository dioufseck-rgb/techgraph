ENV["GENX_PRECOMPILE"]="false"
using Pkg; Pkg.activate(get(ENV,"GENX_ENV","genx_env")); using GenX
for d in sort(readdir(get(ENV,"GENX_SCAN_DIR","scan")))
    try run_genx_case!(joinpath(get(ENV,"GENX_SCAN_DIR","scan"),d)); println("DONE ",d); flush(stdout)
    catch e; println("FAIL ",d," ",e); flush(stdout) end
end
println("SCAN COMPLETE")
