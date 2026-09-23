import csv, io, json, sys, tempfile, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import Store, fit, mixture, align, compare, parse_csv, vector
from app import Workspace, ROOT

class SpectralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.seed=json.loads((ROOT/'data/samples.json').read_text())
    def test_fraction_recovery_and_masks(self):
        candidates=self.seed[:2]
        mix=mixture(candidates,[.65,.35],{})
        result=fit(mix,candidates,{'mode':'fractions'})
        np.testing.assert_allclose([x['value'] for x in result['coefficients']],[.65,.35],atol=1e-6)
        self.assertEqual(result['used_bands'],113)
        self.assertLess(result['rmse'],1e-7)
    def test_sparse_recovery(self):
        mix=mixture(self.seed[:2],[.3,.7],{})
        result=fit(mix,self.seed[:2],{'mode':'sparse','strength':0})
        np.testing.assert_allclose([x['value'] for x in result['coefficients']],[.3,.7],atol=1e-6)
        shrunk=fit(mix,self.seed[:2],{'strength':.1})
        self.assertLess(shrunk['coefficient_sum'],1)
    def test_invalid_reference_band_intersection(self):
        mix=mixture(self.seed[:2],[.3,.7],{})
        mix['values'][20]=None
        result=fit(mix,self.seed[:2],{'mode':'fractions','exclusions':'500:600'})
        self.assertIsNone(result['values'][20]);self.assertLess(result['used_bands'],112)
    def test_resampling_does_not_bridge_gaps(self):
        e=dict(wavelengths=[400,500,600,700,800,1500,1600],values=[1,2,None,4,5,6,7])
        result=align(e,np.array([450,550,650,750,900,1550,1700]),True)
        np.testing.assert_allclose(result[[0,3,5]],[1.5,4.5,6.5])
        self.assertTrue(np.isnan(result[[1,2,4,6]]).all())
        with self.assertRaises(ValueError):align(e,np.array([450,550]),False)
    def test_csv_persistence_edit_and_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Store(Path(folder)/'spectra.csv',self.seed)
            e={**self.seed[0],'name':'Saved pixel'};saved=s.save(e)
            s=Store(s.path,[]);self.assertEqual(len(s.read()),7)
            with self.assertRaises(ValueError):s.save(e)
            s.update(saved['spectrum_id'],{'name':'Renamed','category':'Custom'})
            s.update(saved['spectrum_id'],{'archived':True})
            self.assertEqual(len(s.read()),6);self.assertEqual(len(s.read(True)),7)
            s.update(saved['spectrum_id'],{'archived':False})
            self.assertEqual(len(s.read()),7)
            rows=list(csv.DictReader(io.StringIO(s.to_csv(s.read()))))
            self.assertTrue(any(r['valid']=='0' and r['reflectance']=='' for r in rows))
            imported=parse_csv(s.to_csv(s.read()),'roundtrip.csv','um')
            self.assertEqual(imported[0]['wavelengths'],self.seed[0]['wavelengths'])
    def test_legacy_and_two_column_import(self):
        entries=parse_csv('ID,Material,Category,Description,0.4,0.5,0.6\n1,Roof,Building,test,0.1,0.2,0.3\n','legacy.csv','um')
        self.assertEqual(entries[0]['wavelengths'],[400,500,600])
        e=parse_csv('wavelength,reflectance\n400,0.1\n500,0.2\n600,0.3\n','simple.csv')[0]
        self.assertEqual(e['values'],[.1,.2,.3])
        with self.assertRaises(ValueError):parse_csv('400,.1\n400,.2\n500,.3','bad.csv')
    def test_legacy_blank_rows_auto_units_and_ids(self):
        from engine import LEGACY_GRID_NM
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['ID','Material','Category','Description']+[str(w/1000) for w in LEGACY_GRID_NM])
        writer.writerow(['source-01','Coated panel','Coatings','Test description']+[.2]*80)
        for _ in range(90):writer.writerow(['']*84)
        for filename in ['generic.csv','custom_materials.csv','HELMET_materials.csv']:
            entries=parse_csv(stream.getvalue(),filename)
            self.assertEqual(len(entries),1)
            e=entries[0]
            self.assertEqual(e['source_id'],'source-01')
            self.assertEqual(e['wavelengths'][0],445.5)
            self.assertEqual(e['values'].count(None),20)
            with tempfile.TemporaryDirectory() as folder:
                store=Store(Path(folder)/'library.csv',[])
                store.save(e)
                restored=Store(store.path,[]).read()[0]
                self.assertEqual(restored['source_id'],'source-01')
                self.assertEqual(restored['description'],'Test description')
                self.assertEqual(restored['values'].count(None),20)
                imported=parse_csv(store.to_csv(store.read()),'roundtrip.csv')[0]
                self.assertEqual(imported['source_id'],'source-01')

    def test_noise_reproducible(self):
        a=mixture(self.seed[:2],[.5,.5],{'noise':.01,'seed':7})
        b=mixture(self.seed[:2],[.5,.5],{'noise':.01,'seed':7})
        self.assertEqual(a['values'],b['values'])
        self.assertNotEqual(a['values'],a['clean_values'])
    def test_fraction_validation(self):
        with self.assertRaises(ValueError):mixture(self.seed[:2],[.2,.3],{})
        with self.assertRaises(ValueError):fit(self.seed[0],[],{})
    def test_comparison(self):
        result=compare(self.seed[0],self.seed[:3],{})
        self.assertEqual(result[0]['id'],'demo-0');self.assertAlmostEqual(result[0]['cosine'],1)
        self.assertEqual(len({x['bands'] for x in result}),1)
    def test_cube_pixel_and_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Workspace(Path(folder)/'library.csv',ROOT/'data/demo.img')
            p=w.pixel(215,202)
            result=fit(p,self.seed[:2],{'mode':'fractions'})
            np.testing.assert_allclose([x['value'] for x in result['coefficients']],[.65,.35],atol=.001)
            self.assertEqual(p['values'].count(None),15)
            scores=np.frombuffer(w.scores({'target':p}),'<f4').reshape(360,520)
            self.assertAlmostEqual(float(scores[215,202]),1,places=6)
            with self.assertRaises(ValueError):w.pixel(360,0)
            m=w.meta();self.assertEqual(m['masked'],15)

if __name__=='__main__':unittest.main()
