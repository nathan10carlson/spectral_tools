import sys, tempfile, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from resampling import configuration,resample_spectrum,excluded
from material_analysis import average,rank,duplicates,Preferences
from engine import Store,parse_csv,mixture,fit

class MaterialTests(unittest.TestCase):
    def settings(self):return {**configuration(),'target_grid':[400,450,500,550,600],'bad_ranges':[]}
    def sample(self,name,values):return dict(spectrum_id=name,name=name,category='Test',wavelengths=[400,450,500,550,600],values=values)
    def test_legacy_grid(self):
        s=configuration();self.assertEqual(len(s['target_grid']),80)
        self.assertEqual(excluded(np.array(s['target_grid']),s['bad_ranges']).sum(),20)
    def test_linear_signal_spline_and_no_extrapolation(self):
        t,v=resample_spectrum([400,500,600],[1,2,3],[350,400,450,550,600,650],excluded_ranges=[])
        np.testing.assert_allclose(v[1:5],[1,1.5,2.5,3]);self.assertTrue(np.isnan(v[[0,5]]).all())
    def test_unsampled_excluded_interval_is_not_bridged(self):
        _,v=resample_spectrum([400,500,600,700],[1,2,3,4],[450,510,550,590,650],excluded_ranges=[(520,580)])
        np.testing.assert_allclose(v[[0,4]],[1.5,3.5]);self.assertTrue(np.isnan(v[1:4]).all())
    def test_average_shared_validity_and_csv_provenance(self):
        a=self.sample('A',[1,2,None,4,5]);b=self.sample('B',[3,4,5,6,7]);out=average([a,b],self.settings())
        self.assertEqual(out['used_bands'],4);self.assertIsNone(out['values'][2]);self.assertAlmostEqual(out['standard_deviation'][0],np.sqrt(2))
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'library.csv',[]);store.save(out);read=store.read()[0]
            self.assertEqual(read['contributors'],out['contributors']);self.assertEqual(read['standard_deviation'],out['standard_deviation'])
            parsed=parse_csv(store.path.read_text(),'library.csv')[0]
            self.assertEqual(parsed['contributors'],out['contributors']);self.assertEqual(parsed['standard_deviation'],out['standard_deviation'])
    def test_rank_and_duplicates(self):
        a=self.sample('A',[1,2,3,4,5]);b=self.sample('B',[1,2,3,4,5]);c=self.sample('C',[5,4,3,2,1])
        result=rank(a,[c,b],self.settings());self.assertEqual(result['results'][0]['id'],'B');self.assertEqual(result['used_bands'],5)
        self.assertEqual(len(duplicates([a,b,c],self.settings(),.999)),1)
    def test_fractions_on_configured_grid(self):
        a=self.sample('A',[1,2,3,4,5]);b=self.sample('B',[5,3,2,2,1]);settings=self.settings()
        target=mixture([a,b],[.7,.3],settings)
        result=fit(target,[a,b],{**settings,'mode':'fractions'})
        np.testing.assert_allclose([x['value'] for x in result['coefficients']],[.7,.3],atol=1e-5)
        self.assertEqual(result['wavelengths'],settings['target_grid'])
    def test_range_and_preset_snapshot(self):
        s={**self.settings(),'wavelength_min':450,'wavelength_max':550};a=self.sample('A',[1,2,3,4,5])
        self.assertEqual(rank(a,[a],s)['used_bands'],3)
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(Path(folder)/'library.csv');prefs.category('Vegetation');prefs.preset('Visible',s)
            s['target_grid'][0]=399
            stored=prefs.read();self.assertEqual(stored['presets'][0]['settings']['target_grid'][0],400);self.assertEqual(stored['categories'],['Vegetation'])
if __name__=='__main__':unittest.main()

class ArchivedTests(unittest.TestCase):
    def test_archive_actions_are_atomic_and_only_archived(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'library.csv',[])
            a=store.save(dict(name='A',wavelengths=[400,500,600],values=[1,2,3]))
            with self.assertRaises(ValueError):store.manage_archived([a['spectrum_id']],'delete')
            store.update(a['spectrum_id'],{'archived':True})
            b=store.save(dict(name='A',wavelengths=[400,500,600],values=[3,2,1]))
            with self.assertRaises(ValueError):store.manage_archived([a['spectrum_id']],'restore')
            self.assertTrue(next(e for e in store.read(True) if e['spectrum_id']==a['spectrum_id'])['archived'])
            store.manage_archived([a['spectrum_id']],'delete')
            self.assertEqual([e['spectrum_id'] for e in store.read(True)],[b['spectrum_id']])
            store.update(b['spectrum_id'],{'archived':True});store.manage_archived([b['spectrum_id']],'restore')
            self.assertEqual(len(store.read()),1)

class AutomaticAlignmentTests(unittest.TestCase):
    def test_target_grid_preserved_and_mixture_recovered(self):
        from engine import alignment_preview
        a=dict(spectrum_id='a',name='A',wavelengths=[400,500,600,700],values=[1,2,3,4])
        b=dict(spectrum_id='b',name='B',wavelengths=[400,450,550,650,700],values=[4,3.5,2.5,1.5,1])
        target=dict(name='Pixel',wavelengths=[400,425,475,525,575,625,675,700],values=[.7*(1+(w-400)/100)+.3*(4-(w-400)/100) for w in [400,425,475,525,575,625,675,700]])
        settings={**configuration(),'fit_grid':'target','bad_ranges':[],'mode':'fractions'}
        preview=alignment_preview(target,[a,b],settings);result=fit(target,[a,b],settings)
        self.assertEqual(result['wavelengths'],target['wavelengths']);self.assertEqual(result['used_bands'],preview['used_bands']);self.assertEqual(result['used_bands'],8)
        np.testing.assert_allclose([c['value'] for c in result['coefficients']],[.7,.3],atol=1e-5)
    def test_preview_reports_gaps_and_limits(self):
        from engine import alignment_preview
        target=dict(name='Pixel',wavelengths=[350,400,450,500,550,600,650],values=[1]*7)
        a=dict(spectrum_id='a',name='A',wavelengths=[400,450,500,550,600],values=[1,1,None,1,1])
        settings={**configuration(),'fit_grid':'target','bad_ranges':[]}
        p=alignment_preview(target,[a],settings)
        self.assertEqual(p['status'],['candidate unavailable','usable','usable','candidate unavailable','usable','usable','candidate unavailable'])
        self.assertTrue(p['candidates'][0]['limited']);self.assertEqual(p['used_bands'],4)
