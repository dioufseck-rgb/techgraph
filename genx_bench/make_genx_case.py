import pandas as pd, re, shutil, sys, os
def make(day, dst, src='genx_repo/example_systems/1_three_zones'):
    shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
    os.chdir(dst); h0=day*24
    d=pd.read_csv('system/Demand_data.csv'); zc=[c for c in d.columns if c.startswith('Demand_MW_z')]
    dd=d.iloc[h0:h0+24].reset_index(drop=True); E=['']*23
    out=pd.DataFrame({'Voll':[50000]+E,'Demand_Segment':[1]+E,'Cost_of_Demand_Curtailment_per_MW':[1]+E,
      'Max_Demand_Curtailment':[1]+E,'Rep_Periods':[1]+E,'Timesteps_per_Rep_Period':[24]+E,'Sub_Weights':[8760]+E,'Time_Index':range(1,25)})
    for c in zc: out[c]=dd[c].values
    out.to_csv('system/Demand_data.csv',index=False)
    g=pd.read_csv('system/Generators_variability.csv').iloc[h0:h0+24].copy(); g['Time_Index']=range(1,25); g.to_csv('system/Generators_variability.csv',index=False)
    f=pd.read_csv('system/Fuels_data.csv'); f2=pd.concat([f.iloc[[0]],f.iloc[h0+1:h0+25]]); f2['Time_Index']=[0]+list(range(1,25)); f2.to_csv('system/Fuels_data.csv',index=False)
    t=pd.read_csv('resources/Thermal.csv'); t['Ramp_Up_Percentage']=1.0; t['Ramp_Dn_Percentage']=1.0; t['Min_Power']=0.0; t.to_csv('resources/Thermal.csv',index=False)
    s=open('settings/genx_settings.yml').read()
    for k,v in {'NetworkExpansion':0,'CO2Cap':0,'MinCapReq':0,'UCommit':0,'TimeDomainReduction':0,'CapacityReserveMargin':0,'EnergyShareRequirement':0,'MaxCapReq':0,'OutputFullTimeSeries':0,'WriteShadowPrices':0}.items():
        s=re.sub(rf'^{k}:\s*\d+',f'{k}: {v}',s,flags=re.M)
    open('settings/genx_settings.yml','w').write(s)
    h=open('settings/highs_settings.yml').read().replace('1.0e-05','1.0e-08'); open('settings/highs_settings.yml','w').write(h)
    shutil.rmtree('policies',ignore_errors=True); shutil.rmtree('resources/policy_assignments',ignore_errors=True)
if __name__=='__main__':
    base=os.getcwd()
    for day in map(int,sys.argv[1:]):
        os.chdir(base); make(day, f'scan/day{day:03d}')
