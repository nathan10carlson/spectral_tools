"""Reproducible synthetic benchmark; never reads or modifies user scenes."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scene_unmix import unmix_batch
from fast_unmix import BatchedUnmixer, TileCache, backend_info
from resampling import configuration

rng=np.random.default_rng(7)
w=np.linspace(420,2450,400);X=.05+rng.random((400,8))*.6
weights=rng.random((8,128));weights/=weights.sum(axis=0)
y=X@weights
cube=SimpleNamespace(path='benchmark.img',nb=400,nr=8,nc=16,wl=w,data=y.reshape(400,8,16),masked=np.zeros(400,dtype=bool),scale=1,nodata=None)
materials=[dict(name=f'Material {i}',spectrum_id=str(i),wavelengths=w.tolist(),values=X[:,i].tolist()) for i in range(8)]
report={'description':'Synthetic 400-band / 128-pixel / 8-material test. Speedups are not whole-scene guarantees.','results':[]}
for grid in ['target','configured']:
    settings={**configuration(),'fit_grid':grid,'strength':.001}
    begin=time.perf_counter();reference=unmix_batch(cube,materials,settings,0,128)['pixels'];reference_seconds=time.perf_counter()-begin
    expected=np.array([p['coefficients'] for p in reference]);rmse=np.array([p['rmse'] for p in reference])
    cache=TileCache()
    for profile in ['precise','balanced','fast']:
        begin=time.perf_counter();solver=BatchedUnmixer(cube,materials,settings,cache=cache,accuracy=profile,device='cpu');rows=solver.batch(np.arange(128));seconds=time.perf_counter()-begin
        actual=np.array([p['coefficients'] for p in rows])
        report['results'].append(dict(
            grid=grid,profile=profile,reference_seconds=reference_seconds,
            seconds=seconds,speedup=reference_seconds/seconds,
            max_coefficient_difference=float(np.max(np.abs(expected-actual))),
            max_rmse_difference=float(np.max(np.abs(rmse-np.array([p['rmse'] for p in rows])))),
            converged=sum(p['status'] in ('ok','retried') for p in rows)))
print(json.dumps(report,indent=2))
