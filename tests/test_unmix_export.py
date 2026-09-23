import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from app import Workspace
from unmix_export import export_rectangle


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.cube=SimpleNamespace(nr=3,nc=4,nb=3,wl=np.array([450.,550.,650.]),data=np.arange(36,dtype=float).reshape(3,3,4),masked=np.array([False,False,True]),nodata=-999,scale=10,path='/tmp/source.img')
        self.cube.data[0,1,2]=-999
        self.cube.data[1,2,1]=np.nan
        self.rgb=np.arange(36,dtype=np.uint8).reshape(3,4,3)
        stream=io.BytesIO();Image.fromarray(self.rgb).save(stream,format='PNG');self.png=stream.getvalue()
        self.payload=dict(version=1,bounds=dict(row_start=1,column_start=1,row_end=2,column_end=2),materials=[dict(name='Grass',spectrum_id='grass'),dict(name='Soil',spectrum_id='soil')],channel=0,maximum=1,palette='true',settings=dict(mode='sparse',strength=.001,exclusions='600:700'),retry=dict(enabled=True,ceiling=.1),pixels=[dict(row=r,column=c,status='ok',coefficients=[.1,.9],rmse=.02,strength=.001) for r in range(1,3) for c in range(1,3)])

    def test_archive_coordinates_spectra_and_images(self):
        with export_rectangle(self.cube,self.png,self.payload) as f,zipfile.ZipFile(f) as z:
            self.assertEqual(set(z.namelist()),{'original.png','abundance.png','abundances.csv','spectra.csv','analysis.json'})
            abundance=list(csv.DictReader(io.StringIO(z.read('abundances.csv').decode())))
            self.assertEqual([(p['row'],p['column']) for p in abundance],[('1','1'),('1','2'),('2','1'),('2','2')])
            self.assertEqual(abundance[0]['Grass [grass]'],'0.1')
            spectra=list(csv.DictReader(io.StringIO(z.read('spectra.csv').decode())))
            self.assertEqual(len(spectra),12)
            self.assertEqual(spectra[0]['scaled_value'],'0.5')
            self.assertEqual(spectra[2]['source_valid'],'0')
            self.assertEqual(spectra[2]['raw_value'],'29.0')
            self.assertEqual(spectra[3]['raw_value'],'-999.0')
            self.assertEqual(spectra[3]['scaled_value'],'')
            self.assertEqual(spectra[7]['raw_value'],'')
            self.assertEqual(spectra[7]['source_valid'],'0')
            metadata=json.loads(z.read('analysis.json'))
            self.assertEqual(metadata['bounds'],self.payload['bounds'])
            self.assertEqual(metadata['settings']['exclusions'],'600:700')
            self.assertEqual(metadata['retry']['ceiling'],.1)
            original=np.asarray(Image.open(io.BytesIO(z.read('original.png'))))
            np.testing.assert_array_equal(original[56:58,:2],self.rgb[1:3,1:3])
            image=np.asarray(Image.open(io.BytesIO(z.read('abundance.png'))))
            np.testing.assert_array_equal(image[56,0],[17,38,52])

    def test_partial_and_invalid_pixels_are_not_zeros(self):
        self.payload['pixels'][1].update(status='failed',coefficients=None)
        self.payload['pixels'][3]=dict(row=2,column=2,status='unprocessed',coefficients=None)
        with export_rectangle(self.cube,self.png,self.payload) as f,zipfile.ZipFile(f) as z:
            rows=list(csv.DictReader(io.StringIO(z.read('abundances.csv').decode())))
            self.assertEqual(rows[1]['Grass [grass]'],'')
            self.assertEqual(rows[3]['status'],'unprocessed')
            image=np.asarray(Image.open(io.BytesIO(z.read('abundance.png'))))
            np.testing.assert_array_equal(image[56,1],[81,87,99])

    def test_invalid_bounds_pixel_order_and_size(self):
        self.payload['bounds']['row_end']=3
        with self.assertRaises(ValueError):export_rectangle(self.cube,self.png,self.payload)
        self.payload['bounds']['row_end']=2
        self.payload['pixels'].reverse()
        with self.assertRaises(ValueError):export_rectangle(self.cube,self.png,self.payload)
        with patch('unmix_export.MAX_SPECTRAL_ROWS',2):
            with self.assertRaises(ValueError):export_rectangle(self.cube,self.png,self.payload)

    def test_empty_startup_preserves_existing_library(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'library.csv'
            w=Workspace(path)
            self.assertIsNone(w.meta())
            self.assertEqual(w.store.read(),[])
            w.store.save(dict(name='Measured',wavelengths=[400,500,600],values=[.1,.2,.3]))
            reopened=Workspace(path)
            self.assertEqual(reopened.store.read()[0]['name'],'Measured')
            self.assertIsNone(reopened.meta())


if __name__=='__main__':unittest.main()
