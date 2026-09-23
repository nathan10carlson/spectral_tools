"""Illustrative synthetic materials and scene. No measured sensor/material data."""
from pathlib import Path
import json
import numpy as np

def generate(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    wl=np.linspace(420,2450,128);u=wl/1000
    dip=lambda c,s:np.exp(-.5*((u-c)/s)**2)
    spectra=[.045+.43/(1+np.exp(-(u-.73)/.028))-.13*dip(1.45,.085)-.20*dip(1.94,.12),
             .11+.21*(u-.42)/2.03-.07*dip(2.2,.085),
             .035*np.exp(-(u-.45)*2.5)+.008,
             .27+.055*np.sin(u*1.7)-.035*dip(2.3,.09),
             .12+.14/(1+np.exp(-(u-.62)/.07))-.05*dip(2.2,.08),
             .065+.018*np.sin(u*2.5)]
    names=['Meadow grass','Dry mineral soil','Open water','Light concrete','Terracotta roof','Asphalt']
    categories=['Vegetation','Soil','Water','Built surfaces','Built surfaces','Built surfaces']
    mask=((wl>=1350)&(wl<=1450))|((wl>=1800)&(wl<=1950))
    entries=[]
    for i,(name,category,v) in enumerate(zip(names,categories,spectra)):
        entries.append(dict(spectrum_id=f'demo-{i}',name=name,category=category,description='Illustrative synthetic spectrum. Not a measured material signature.',source='HELMET synthetic collection',saved_utc='',archived=False,wavelengths=wl.tolist(),values=[None if mask[j] else float(x) for j,x in enumerate(v)]))
    h,w=360,520;y,x=np.mgrid[:h,:w];labels=np.zeros((h,w),int)
    labels[(x<195)&(y<140)]=1;labels[(x<180)&(y>180)]=1
    labels[((x-405)/89)**2+((y-70)/55)**2<1]=2
    labels[(x>295)&(y>170)]=3
    labels[(abs(x-240)<13)|(abs(y-160)<10)]=5
    for yy in [205,255,305]:
        for xx in [330,400,470]:labels[yy:yy+29,xx:xx+38]=4
    rng=np.random.default_rng(41)
    texture=.91+.06*rng.random((h,w))+.035*np.sin(x*.4)*np.sin(y*.25)
    field=(labels==1);texture[field]*=(.88+.12*(np.sin((x[field]+y[field]*.25)*.32)>0))
    a=np.asarray(spectra)[:,None,None,:] if False else np.asarray(spectra)
    cube=(a[labels]*texture[...,None]).transpose(2,0,1)
    # A mixed meadow/soil strip provides a known mixture example.
    cube[:,180:250,190:215]=(.65*a[0]+.35*a[1])[:,None,None]
    cube[mask]=0
    cube=np.clip(cube*10000,0,65535).astype('<u2')
    cube.tofile(folder/'demo.img')
    (folder/'demo.hdr').write_text('ENVI\nsamples = 520\nlines = 360\nbands = 128\ndata type = 12\nbyte order = 0\ninterleave = bsq\nreflectance scale factor = 10000\nwavelength units = nm\nwavelength = {'+','.join(map(str,wl))+'}\nbbl = {'+','.join(str(int(not v)) for v in mask)+'}\n')
    (folder/'samples.json').write_text(json.dumps(entries))
    return entries
if __name__=='__main__':generate(Path(__file__).parent/'data')
