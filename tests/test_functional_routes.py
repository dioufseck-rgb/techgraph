from techgraph.measurement.functional_routes import simple_paths,path_edges,competitive_route_summary

def test_simple_paths_and_edges():
    p=simple_paths(['A','B','C'],{('A','B'),('B','C'),('A','C')},'A','C')
    assert set(p)=={('A','C'),('A','B','C')}
    assert path_edges(('A','B','C'))==frozenset({('A','B'),('B','C')})

def test_competitive_route_summary_distinguishes_feasible_from_competitive():
    rec=[
      {'status':'Optimal','all_path_installed':True,'premium_pct':.012},
      {'status':'Optimal','all_path_installed':True,'premium_pct':.031},
      {'status':'Optimal','all_path_installed':False,'premium_pct':.001},
      {'status':'FAILED','all_path_installed':True,'premium_pct':0.},
    ]
    s=competitive_route_summary(rec,100.)
    assert s['functional_route_count']==2
    assert s['competitive_routes_1pct']==0
    assert s['competitive_routes_2pct']==1
    assert s['competitive_routes_5pct']==2
    assert abs(s['best_functional_route_premium_pct']-.012)<1e-12
