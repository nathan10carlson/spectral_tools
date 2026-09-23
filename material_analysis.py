"""Library exploration, equal-weight averages, and saved comparison settings."""
import json, os, tempfile
from pathlib import Path
import numpy as np
from engine import prepare, vector, clean, safe_name
from resampling import configuration

def settings_for(data):
    settings={**configuration(),**data}
    grid=np.asarray(settings['target_grid'],float)
    if grid.ndim!=1 or len(grid)<3 or len(grid)>10000 or not np.isfinite(grid).all() or np.any(np.diff(grid)<=0):raise ValueError('Preset has invalid target bands.')
    low,high=settings.get('wavelength_min'),settings.get('wavelength_max')
    if any(v is not None and not np.isfinite(float(v)) for v in (low,high)):raise ValueError('Wavelength bounds must be finite.')
    if low is not None and high is not None and float(low)>=float(high):raise ValueError('Wavelength minimum must be below maximum.')
    return settings

class Preferences:
    def __init__(self,path):self.path=Path(path).with_suffix('.settings.json')
    def read(self):
        if not self.path.exists():return {'categories':[],'presets':[]}
        return json.loads(self.path.read_text())
    def write(self,data):
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.settings-')
        try:
            with os.fdopen(fd,'w') as f:json.dump(data,f,allow_nan=False);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def category(self,name):
        name=safe_name(name);data=self.read()
        if name.casefold() not in [x.casefold() for x in data['categories']]:data['categories'].append(name)
        self.write(data);return data
    def preset(self,name,settings):
        name=safe_name(name);settings=settings_for(settings);data=self.read()
        existing=next((p for p in data['presets'] if p['name'].casefold()==name.casefold()),None)
        record={'name':name,'settings':settings}
        if existing:existing.update(record)
        else:data['presets'].append(record)
        self.write(data);return data

def average(entries,settings):
    if len(entries)<2:raise ValueError('Select at least two spectra to average.')
    aligned=[prepare(e,settings) for e in entries]
    A=np.array([vector(e) for e in aligned]);valid=np.isfinite(A).all(axis=0)
    if valid.sum()<3:raise ValueError('Fewer than three bands are valid in every selected spectrum.')
    mean=np.full(A.shape[1],np.nan);std=mean.copy()
    mean[valid]=A[:,valid].mean(axis=0);std[valid]=A[:,valid].std(axis=0,ddof=1)
    return dict(name='Average spectrum',category='Averages',source='Library average',
                description='Equal-weight mean; sample standard deviation across '+str(len(entries))+' spectra. All contributors required at each band.',
                contributors=[{'id':e['spectrum_id'],'name':e['name']} for e in entries],
                wavelengths=aligned[0]['wavelengths'],values=clean(mean),standard_deviation=clean(std),used_bands=int(valid.sum()))

def rank(target,candidates,settings):
    target=prepare(target,settings);aligned=[prepare(e,settings) for e in candidates]
    if not aligned:raise ValueError('No candidates match the selected search scope.')
    y=vector(target);A=np.array([vector(e) for e in aligned]);valid=np.isfinite(y)&np.isfinite(A).all(axis=0)
    if valid.sum()<3:raise ValueError('Fewer than three common valid bands. Narrow the search scope or change the range.')
    yv=y[valid];yn=np.linalg.norm(yv)
    if yn==0:raise ValueError('Target has zero signal in this range.')
    results=[]
    for e,x in zip(aligned,A):
        xv=x[valid];norm=np.linalg.norm(xv)
        if norm==0:continue
        score=float(np.clip(xv@yv/norm/yn,-1,1));res=np.full(len(y),np.nan);res[valid]=yv-xv
        results.append(dict(id=e['spectrum_id'],name=e['name'],category=e.get('category',''),color=e.get('color'),cosine=score,angle=float(np.degrees(np.arccos(score))),rmse=float(np.sqrt(np.mean(res[valid]**2))),bands=int(valid.sum()),spectrum=e,residual={'name':'Target − candidate','wavelengths':target['wavelengths'],'values':clean(res)}))
    results.sort(key=lambda e:e['rmse'] if settings.get('rank')=='rmse' else e['angle'])
    if not results:raise ValueError('Candidates have zero signal in this range.')
    return {'target':target,'results':results,'used_bands':int(valid.sum())}

def duplicates(entries,settings,threshold=.995,max_rmse=None):
    if len(entries)>500:raise ValueError('Choose at most 500 spectra per duplicate review using selections or a category filter.')
    if not np.isfinite(threshold) or not -1<=threshold<=1:raise ValueError('Cosine threshold must be between -1 and 1.')
    aligned=[prepare(e,settings) for e in entries];rows=[]
    if max_rmse is not None and (not np.isfinite(max_rmse) or max_rmse<0):raise ValueError('RMSE limit must be nonnegative.')
    for i,a in enumerate(aligned):
        x=vector(a)
        for b in aligned[i+1:]:
            y=vector(b);valid=np.isfinite(x)&np.isfinite(y)
            if valid.sum()<3:continue
            norm=np.linalg.norm(x[valid])*np.linalg.norm(y[valid])
            if norm==0:continue
            cos=float(np.clip(x[valid]@y[valid]/norm,-1,1));rmse=float(np.sqrt(np.mean((x[valid]-y[valid])**2)))
            if cos>=threshold and (max_rmse is None or rmse<=max_rmse):rows.append(dict(first=a,second=b,cosine=cos,rmse=rmse,bands=int(valid.sum())))
    return sorted(rows,key=lambda r:(-r['cosine'],r['rmse']))
