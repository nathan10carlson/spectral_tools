"""Generate a temporary 512x512x420 cube and profile 12-material unmixing.

Run with venv/bin/python benchmarks/profile_scene.py --case similar.
Only a reproducible sample is solved by default; projected time is an estimate.
No user images or libraries are read or modified.
"""
import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import sys
import tempfile
import time
from types import SimpleNamespace
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fast_unmix import BatchedUnmixer
from resampling import configuration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['distinct', 'similar'], default='distinct')
    parser.add_argument('--pixels', type=int, default=2048)
    parser.add_argument('--profile', choices=['fast', 'balanced', 'precise'], default='balanced')
    args = parser.parse_args()
    if not 1 <= args.pixels <= 512*512:parser.error('pixels must be between 1 and 262144')
    rng = np.random.default_rng(19)
    w = np.linspace(400, 2450, 420)
    x = (w-w[0])/(w[-1]-w[0])
    spectra = np.array([.12+.35*np.exp(-((x-center)/.13)**2)+.05*x
                        for center in np.linspace(0, 1, 12)]).T
    if args.case == 'similar':spectra = .2+.15*x[:, None]+.08*spectra
    materials = [dict(spectrum_id=str(i), name=f'Synthetic {i}', wavelengths=w.tolist(),
                      values=spectra[:, i].tolist()) for i in range(12)]
    with tempfile.TemporaryDirectory(prefix='helmet-profile-') as folder:
        path = Path(folder)/'synthetic.img'
        data = np.memmap(path, dtype='float32', mode='w+', shape=(420, 512, 512))
        flat = data.reshape(420, -1)
        for start in range(0, 512*512, 4096):
            weights = rng.random((12, 4096))
            weights[weights < .8] = 0
            weights[0] += .01
            weights /= weights.sum(axis=0)
            flat[:, start:start+4096] = spectra@weights+rng.normal(0, .0005, (420, 4096))
        data.flush()
        path.with_suffix('.hdr').write_text('ENVI\nsamples = 512\nlines = 512\nbands = 420\ndata type = 4\ninterleave = bsq\nbyte order = 0\nwavelength units = Nanometers\nwavelength = {'+','.join(map(str, w))+'}\n')
        cube = SimpleNamespace(path=str(path), nb=420, nr=512, nc=512, wl=w, data=data,
                               masked=np.zeros(420, bool), scale=1, nodata=None)
        solver = BatchedUnmixer(cube, materials, {**configuration(), 'fit_grid':'configured',
                                  'strength':.001}, accuracy=args.profile, device='cpu')
        profiler = cProfile.Profile()
        start = time.perf_counter()
        profiler.enable()
        rows = solver.batch(np.arange(args.pixels))
        profiler.disable()
        elapsed = time.perf_counter()-start
        print(json.dumps(dict(case=args.case, shape=[512,512,420], candidates=12,
            pixels=args.pixels, seconds=elapsed, projected_scene_seconds=elapsed*512*512/args.pixels,
            used_bands=rows[0]['used_bands'], accuracy=args.profile,
            iteration_percentiles=np.percentile([r['iterations'] for r in rows], [50,95,100]).tolist(),
            retried=sum(r['attempts']>1 for r in rows), failed=sum(r['status']=='failed' for r in rows)), indent=2))
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats('cumulative').print_stats(12)
        print(stream.getvalue())


if __name__ == '__main__':main()
