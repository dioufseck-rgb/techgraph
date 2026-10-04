from analyze_demand_sweep import stats, tv

def test_distribution_preserves_reversals_and_ties():
    s=stats(x for x in [-3,0,0,2,6])
    assert (s['lower'],s['tied'],s['higher'])==(1,2,2)
    assert s['median']==0 and s['minimum']==-3 and s['maximum']==6

def test_functional_share_distance():
    assert tv({'A':1.},{'B':1.})==1.
    assert tv({'A':.7,'B':.3},{'A':.7,'B':.3})==0.
    assert abs(tv({'A':1.},{'A':.7,'B':.3})-.3)<1e-12
    assert tv({'A':.2,'B':.8},{'A':.6,'B':.4})==tv({'A':.6,'B':.4},{'A':.2,'B':.8})
