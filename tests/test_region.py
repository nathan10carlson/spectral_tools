import sys,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from region import region_average
class RegionTests(unittest.TestCase):
    def cube(self):return SimpleNamespace(nr=2,nc=2,nb=4,wl=np.array([400,500,600,700]),data=np.array([[[2,4],[6,8]],[[2,-999],[6,8]],[[2,4],[6,8]],[[2,4],[6,8]]]),masked=np.array([False,False,False,True]),nodata=-999,scale=2,path='test.img')
    def test_mean_variability_and_masks(self):
        r=region_average(self.cube(),dict(row_start=0,row_end=1,column_start=0,column_end=1))
        self.assertEqual(r['pixel_count'],4);self.assertEqual(r['valid_counts'],[4,3,4,0]);self.assertEqual(r['values'],[2.5,8/3,2.5,None]);self.assertAlmostEqual(r['standard_deviation'][0],np.std([1,2,3,4],ddof=1));self.assertIsNone(r['standard_deviation'][3])
    def test_bounds_and_single_sample(self):
        with self.assertRaises(ValueError):region_average(self.cube(),dict(row_start=0,row_end=0,column_start=0,column_end=0))
        with self.assertRaises(ValueError):region_average(self.cube(),dict(row_start=-1,row_end=1,column_start=0,column_end=1))
        r=region_average(self.cube(),dict(row_start=0,row_end=0,column_start=0,column_end=1));self.assertEqual(r['valid_counts'][1],1);self.assertIsNone(r['standard_deviation'][1])
