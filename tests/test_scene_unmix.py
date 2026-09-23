import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from engine import fit
from scene_unmix import unmix_batch


class SceneUnmixTests(unittest.TestCase):
    def setUp(self):
        self.w = np.array([400., 500., 600., 700., 800.])
        self.materials = [dict(spectrum_id='grass', name='Grass', wavelengths=self.w.tolist(), values=[.1,.2,.7,.8,.6]), dict(spectrum_id='soil', name='Soil', wavelengths=self.w.tolist(), values=[.6,.5,.4,.3,.2])]
        a = np.array([e['values'] for e in self.materials]).T
        self.cube = SimpleNamespace(nr=2, nc=2, wl=self.w, data=(a @ np.array([[.1,.9,.4,.6],[.9,.1,.6,.4]])).reshape(5,2,2)*1000, masked=np.zeros(5,dtype=bool), nodata=-999, scale=1000)

    def test_coefficients_coordinates_and_pixel_parity(self):
        for mode in ['sparse','fractions']:
            settings=dict(mode=mode, strength=0, fit_grid='target')
            result=unmix_batch(self.cube,self.materials,settings,0,4)
            self.assertEqual(result['next'],4)
            for i,p in enumerate(result['pixels']):
                r,c=divmod(i,2)
                target=dict(wavelengths=self.w.tolist(),values=(self.cube.data[:,r,c]/1000).tolist())
                expected=fit(target,self.materials,settings)
                np.testing.assert_allclose(p['coefficients'],[v['value'] for v in expected['coefficients']],atol=1e-8)
                self.assertEqual((p['row'],p['column']),(r,c))
            np.testing.assert_allclose([p['coefficients'][0] for p in result['pixels']],[.1,.9,.4,.6],atol=1e-5)

    def test_configured_grid_and_mask_parity(self):
        self.cube.masked[0]=True
        self.cube.data[1,0,1]=-999
        settings=dict(mode='sparse',strength=.001,target_grid=[400,450,500,550,600,650,700,750,800],resample=True,interpolation='linear')
        result=unmix_batch(self.cube,self.materials,settings,0,2)
        for p in result['pixels']:
            raw=self.cube.data[:,p['row'],p['column']]
            target=dict(wavelengths=self.w.tolist(),values=[None if masked or v==-999 else v/1000 for v,masked in zip(raw,self.cube.masked)])
            expected=fit(target,self.materials,settings)
            np.testing.assert_allclose(p['coefficients'],[v['value'] for v in expected['coefficients']],atol=1e-8)

    def test_invalid_and_partial_batch(self):
        self.cube.data[:,0,0]=-999
        result=unmix_batch(self.cube,self.materials,{},0,1)
        self.assertEqual(result['pixels'][0]['status'],'invalid')
        self.assertIsNone(result['pixels'][0]['coefficients'])
        self.assertEqual(unmix_batch(self.cube,self.materials,{},3,64)['next'],4)
        with self.assertRaises(ValueError):unmix_batch(self.cube,self.materials,{},4,1)

    def test_retry_only_nonconvergence_and_preserve_strength(self):
        actual=fit
        def first_fails(*args,**kwargs):
            if args[2]['strength']<.01:raise ValueError('Sparse solver did not converge. Reduce redundant candidates or change sparsity.')
            return actual(*args,**kwargs)
        with patch('scene_unmix.fit',side_effect=first_fails):
            p=unmix_batch(self.cube,self.materials,{'strength':.001},0,1)['pixels'][0]
            self.assertEqual((p['status'],p['strength'],p['attempts']),('retried',.01,2))
            p=unmix_batch(self.cube,self.materials,{'strength':.001},0,1,retry=False)['pixels'][0]
            self.assertEqual(p['status'],'failed')
        with patch('scene_unmix.fit',side_effect=ValueError('Sparse solver did not converge.')):
            p=unmix_batch(self.cube,self.materials,{'strength':.001},0,1,ceiling=.1)['pixels'][0]
            self.assertEqual((p['status'],p['strength'],p['attempts']),('failed',.1,3))


if __name__=='__main__':unittest.main()
