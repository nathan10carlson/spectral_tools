import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from engine import prepare, vector, fit, sparse_fit
from fast_unmix import BatchedUnmixer, TileCache, resample_tile, spectral_settings, sparse_cpu, PROFILES
from unmix_jobs import RunManager


class FastTests(unittest.TestCase):
    def fixture(self,pixels=24,bands=80):
        rng=np.random.default_rng(4)
        w=np.linspace(420,2400,bands);X=.04+rng.random((bands,4))*.7
        a=rng.random((4,pixels));a/=a.sum(axis=0)
        cube=SimpleNamespace(nr=1,nc=pixels,nb=bands,wl=w,data=(X@a).reshape(bands,1,pixels),masked=np.zeros(bands,bool),nodata=-999,scale=1,path='test.img')
        candidates=[dict(spectrum_id=str(i),name=f'Material {i}',wavelengths=w.tolist(),values=X[:,i].tolist()) for i in range(4)]
        return cube,candidates

    def test_batched_matches_reference_with_masks_and_repeated_gram(self):
        cube,materials=self.fixture();cube.data[8,0,1]=-999;cube.data[:,0,2]=-999
        cube.masked[20]=True
        settings=dict(fit_grid='target',strength=.001,mode='sparse')
        solver=BatchedUnmixer(cube,materials,settings,accuracy='precise',device='cpu')
        rows=solver.batch(np.arange(24))
        self.assertEqual(rows[2]['status'],'invalid')
        for i,row in enumerate(rows):
            if i==2:continue
            raw=cube.data[:,0,i];values=np.where(cube.masked|(raw==-999),np.nan,raw)
            target=dict(wavelengths=cube.wl.tolist(),values=[None if not np.isfinite(v) else v for v in values])
            expected=fit(target,materials,settings)
            np.testing.assert_allclose(row['coefficients'],[x['value'] for x in expected['coefficients']],atol=1e-9)
        count=len(solver.grams);solver.batch(np.arange(24));self.assertEqual(len(solver.grams),count)
        self.assertGreater(solver.cache.hits,0)

    def test_resampling_matches_individual_preparation(self):
        cube,_=self.fixture(bands=400);cube.data[30:36,0,1]=-999;cube.data[75,0,5]=np.nan;cube.masked[200]=True
        for method in ['linear','pchip','cubic_spline']:
            settings=dict(target_grid=np.linspace(440,2300,80).tolist(),interpolation=method,bad_ranges=[[900,1000],[1700,None]],exclusions='1100:1150',wavelength_min=500,wavelength_max=1650)
            result=resample_tile(cube,np.arange(24),settings)
            for i in range(24):
                raw=cube.data[:,0,i];raw=np.where(cube.masked|(raw==-999),np.nan,raw)
                expected=vector(prepare(dict(wavelengths=cube.wl.tolist(),values=[None if not np.isfinite(v) else v for v in raw]),settings))
                np.testing.assert_allclose(result[:,i],expected,atol=1e-12,equal_nan=True)

    def test_cache_reuses_after_restart_and_invalidates_grid(self):
        cube,_=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            a=TileCache(folder,memory_bytes=1)
            settings=dict(target_grid=cube.wl.tolist())
            one=a.get(cube,settings,np.arange(24),{'source':'one'})
            b=TileCache(folder)
            np.testing.assert_array_equal(b.get(cube,settings,np.arange(24),{'source':'one'}),one)
            self.assertEqual((b.hits,b.misses),(1,0))
            settings['wavelength_min']=1000;b.get(cube,settings,np.arange(24),{'source':'one'})
            self.assertEqual(b.misses,1)
            b.get(cube,settings,np.arange(24),{'source':'two'});self.assertEqual(b.misses,2)

    def test_accuracy_and_zero_strength(self):
        cube,materials=self.fixture(bands=400);X=np.array([e['values'] for e in materials]).T;Y=cube.data[:,0,:]
        G=X.T@X/400;B=X.T@Y/400
        reference=np.array([sparse_fit(X,y,0)[0] for y in Y.T]).T
        for profile in PROFILES:
            answer,ok,iterations,kkt=sparse_cpu(G,B,0,profile)
            self.assertTrue(ok.all())
            error=np.max(np.abs(answer-reference))
            self.assertLess(error,{'fast':2e-4,'balanced':2e-6,'precise':1e-9}[profile])
            self.assertTrue((answer>=0).all())

    def test_correlated_candidates_preserve_precise_objective(self):
        rng=np.random.default_rng(8);X=rng.random((80,4));X[:,1]=X[:,0]*.999+X[:,1]*.001
        X[:,3]=X[:,2]  # Duplicate materials are permitted but coefficients are ambiguous.
        Y=X@rng.random((4,6));G=X.T@X/80;B=X.T@Y/80
        answer,ok,_,_=sparse_cpu(G,B,.02,'precise')
        for i in range(6):
            old,_,converged,_=sparse_fit(X,Y[:,i],.02)
            self.assertEqual(ok[i],converged)
            np.testing.assert_allclose(X@answer[:,i],X@old,atol=1e-9)

    def test_fraction_mode_preserves_constraints_and_pruning(self):
        cube,materials=self.fixture(pixels=3)
        settings=dict(fit_grid='target',mode='fractions',max_materials=2)
        rows=BatchedUnmixer(cube,materials,settings,device='cpu').batch(np.arange(3))
        for row in rows:
            self.assertEqual(row['status'],'ok');self.assertAlmostEqual(sum(row['coefficients']),1,places=7)
            self.assertLessEqual(np.count_nonzero(row['coefficients']),2)

    def test_pause_inside_solver_and_gpu_fallback(self):
        stop=threading.Event();stop.set()
        with self.assertRaises(InterruptedError):sparse_cpu(np.eye(2),np.ones((2,3)),.001,cancel=stop)
        cube,materials=self.fixture(pixels=3)
        with patch('fast_unmix.backend_info',return_value=dict(devices=['cpu'],message='No GPU available.')):
            solver=BatchedUnmixer(cube,materials,{},device='mps');rows=solver.batch(np.arange(3))
            self.assertEqual(solver.device,'cpu');self.assertIn('fallback',solver.device_message)
            self.assertTrue(all(p['status']=='ok' for p in rows))

    def test_gpu_runtime_error_falls_back_to_cpu(self):
        cube,materials=self.fixture(pixels=3)
        with patch('fast_unmix.backend_info',return_value=dict(devices=['cpu','mps'],message='GPU')),patch('fast_unmix.sparse_gpu',side_effect=RuntimeError('Test GPU failure')):
            solver=BatchedUnmixer(cube,materials,{},device='mps')
            rows=solver.batch(np.arange(3))
            self.assertEqual(solver.device,'cpu');self.assertIn('Test GPU failure',solver.device_message)
            self.assertTrue(all(p['status']=='ok' for p in rows))

    def test_retry_only_unconverged_pixels(self):
        cube,materials=self.fixture(pixels=3);solver=BatchedUnmixer(cube,materials,{'strength':.001},device='cpu')
        original=solver.solve
        def fail_initial(G,B,strength):
            a,ok,iterations,kkt=original(G,B,strength)
            if strength==.001:ok[0]=False
            return a,ok,iterations,kkt
        with patch.object(solver,'solve',side_effect=fail_initial):rows=solver.batch(np.arange(3))
        self.assertEqual([p['attempts'] for p in rows],[2,1,1]);self.assertEqual(rows[0]['strength'],.01)
        self.assertEqual(rows[0]['status'],'retried')

    def test_memory_bounded_batch_size_and_partition_parity(self):
        cube,materials=self.fixture(pixels=48)
        solver=BatchedUnmixer(cube,materials,{},device='cpu')
        self.assertEqual(solver.batch_size(),16384)
        whole=solver.batch(np.arange(48))
        split=solver.batch(np.arange(17))+solver.batch(np.arange(17,48))
        np.testing.assert_allclose([p['coefficients'] for p in whole],[p['coefficients'] for p in split],atol=1e-12)
        solver.w=np.arange(10000)
        self.assertLess(solver.batch_size(),2048)
        solver.settings={'mode':'fractions'}
        self.assertEqual(solver.batch_size(),2048)

    def test_checkpoint_pause_restart_resume_and_source_change(self):
        cube,materials=self.fixture(pixels=4100)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'scene.img';cube.data.tofile(source);cube.path=str(source)
            root=Path(folder)/'runs';manager=RunManager(root);self.addCleanup(manager.close)
            original=BatchedUnmixer.batch
            def stop_after_first(solver,indices):
                result=original(solver,indices);manager.cancel.set();return result
            with patch.object(BatchedUnmixer,'batch',stop_after_first), patch.object(BatchedUnmixer,'batch_size',return_value=2048):
                record=manager.start(cube,dict(name='scene.img',rows=1,cols=4100,bands=80,version=1),materials,{},device='cpu')
                manager.thread.join(10)
            status=manager.info(record['id']);self.assertEqual(status['done'],2048);self.assertEqual(status['state'],'paused')
            manager.close();restarted=RunManager(root);self.addCleanup(restarted.close)
            restarted.resume(cube,record['id']);restarted.thread.join(15)
            status=restarted.info(record['id']);self.assertEqual((status['done'],status['state']),(4100,'complete'))
            first=restarted.status(record['id'],0,4096);last=restarted.status(record['id'],first['cursor'])
            self.assertEqual(first['cursor'],4096);self.assertEqual(last['cursor'],4100)
            self.assertEqual(last['pixels'][-1]['column'],4099)
            source.write_bytes(b'changed')
            with self.assertRaises(ValueError):restarted.resume(cube,record['id'])

    def test_preview_coordinates_and_saved_snapshot(self):
        cube,materials=self.fixture(pixels=30);cube.nr=5;cube.nc=6;cube.data=cube.data.reshape(cube.nb,5,6)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'scene.img';cube.data.tofile(source);cube.path=str(source)
            manager=RunManager(Path(folder)/'runs');self.addCleanup(manager.close)
            record=manager.start(cube,dict(name='scene.img'),materials,{},device='cpu',bounds=dict(row_start=2,row_end=3,column_start=1,column_end=3),preview=True)
            manager.thread.join(10)
            page=manager.status(record['id']);self.assertEqual(page['run']['total'],6)
            self.assertEqual([(p['row'],p['column']) for p in page['pixels']],[(2,1),(2,2),(2,3),(3,1),(3,2),(3,3)])
            materials[0]['name']='Edited later'
            self.assertNotEqual(manager.info(record['id'])['materials'][0]['name'],'Edited later')


if __name__=='__main__':unittest.main()
