"""Shared spectral storage, band alignment, comparison, and unmixing."""
import csv, io, json, os, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from resampling import resample_spectrum, excluded
def sparse_fit(A, y, strength):
    """min_a>=0 ||y-Aa||²/(2m) + alpha*sum(a); alpha relative to alpha_max.

    No intercept, centering, column normalization, or sum-to-one constraint.
    KKT residual checks convergence. Raw coefficients retain radiometric scale.
    """
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Sparsity strength must be between 0 and 1.')
    m, n = A.shape
    G = A.T @ A / m
    b = A.T @ y / m
    if np.any(np.diag(G) <= 1e-20):
        raise ValueError('A candidate is zero on the shared valid bands.')
    alpha = strength * max(0., float(b.max()))
    a = np.zeros(n)
    tolerance = 1e-9 * max(float(np.max(np.abs(b))), 1e-12)
    converged = False
    for iteration in range(20000):
        for j in range(n):
            a[j] = max(0., a[j] + (b[j] - G[j] @ a - alpha) / G[j, j])
        gradient = G @ a - b + alpha
        kkt = np.max(np.where(a > 0, np.abs(gradient), np.maximum(-gradient, 0)))
        if kkt <= tolerance:
            converged = True
            break
    return a, alpha, converged, iteration + 1



FIELDS=['spectrum_id','name','category','description','source','saved_utc','archived','band_index','band_center_nm','reflectance','valid','source_id','standard_deviation','contributors']
PALETTE=['#ac89ff','#40cba3','#f5b76a','#65aaff','#e788b9','#9faec0','#cbd985']

def clean(values):
    return [float(v) if np.isfinite(v) else None for v in values]

def vector(entry):
    return np.array([np.nan if v is None else v for v in entry['values']],float)

def safe_name(value):
    name=str(value).strip()
    if not name or len(name)>100 or any(ord(c)<32 for c in name) or name[0] in '=+-@':
        raise ValueError('Enter a name of 1–100 characters without a leading =, +, -, or @.')
    return name

def validate(entry):
    w=np.asarray(entry['wavelengths'],float); v=vector(entry)
    if w.ndim!=1 or len(w)!=len(v) or len(w)<3 or not np.isfinite(w).all() or np.any(np.diff(w)<=0):
        raise ValueError('Band centers must be finite, unique, and increasing, with at least three bands.')
    if np.isfinite(v).sum()<3: raise ValueError('At least three valid reflectance samples are required.')
    entry['name']=safe_name(entry['name'])
    entry['values']=clean(v)
    entry['wavelengths']=w.tolist()
    return entry

class Store:
    def __init__(self,path,seed):
        self.path=Path(path); self.lock=threading.RLock(); self.seed=seed
    def read(self,archived=False):
        with self.lock:
            entries=[]
            if self.path.exists():
                groups={}
                with self.path.open(newline='',encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        sid=row['spectrum_id']
                        if sid not in groups:
                            groups[sid]={k:row.get(k,'') for k in FIELDS[:7]}
                            groups[sid].update(wavelengths=[],values=[],standard_deviation=[],contributors=json.loads(row.get('contributors') or '[]'))
                        e=groups[sid]
                        e['source_id']=row.get('source_id','')
                        e['standard_deviation'].append(float(row['standard_deviation']) if row.get('standard_deviation') else None)
                        if int(row['band_index'])!=len(e['values']): raise ValueError('Invalid library band ordering.')
                        e['wavelengths'].append(float(row['band_center_nm']))
                        e['values'].append(float(row['reflectance']) if row['valid']=='1' and row['reflectance'] else None)
                entries=list(groups.values())
            else: entries=json.loads(json.dumps(self.seed))
            for i,e in enumerate(entries):
                e['color']=PALETTE[i%len(PALETTE)]
                e['archived']=str(e.get('archived','0')).lower() in ('1','true')
            return entries if archived else [e for e in entries if not e['archived']]
    @staticmethod
    def to_csv(entries):
        stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
        for e in entries:
            for i,(w,v) in enumerate(zip(e['wavelengths'],e['values'])):
                row={k:e.get(k,'') for k in FIELDS[:7]};row['archived']=int(bool(e.get('archived',False)))
                row['source_id']=e.get('source_id','')
                std=e.get('standard_deviation',[])
                row['standard_deviation']=std[i] if i<len(std) and std[i] is not None else ''
                row['contributors']=json.dumps(e.get('contributors',[]))
                row.update(band_index=i,band_center_nm=w,reflectance='' if v is None else v,valid=int(v is not None))
                writer.writerow(row)
        return stream.getvalue()
    def write(self,entries):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.library-',suffix='.csv')
        try:
            with os.fdopen(fd,'w',newline='',encoding='utf-8') as f:
                f.write(self.to_csv(entries));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def save(self,entry):
        validate(entry)
        with self.lock:
            entries=self.read(True)
            if any(e['name'].casefold()==entry['name'].casefold() and not e['archived'] for e in entries):
                raise ValueError('That name is already in the library. Please choose another.')
            entry={**entry,'spectrum_id':uuid.uuid4().hex,'saved_utc':datetime.now(timezone.utc).isoformat(),'archived':False}
            entries.append(entry);self.write(entries)
        return entry
    def update(self,sid,changes):
        with self.lock:
            entries=self.read(True);e=next((e for e in entries if e['spectrum_id']==sid),None)
            if e is None: raise ValueError('Spectrum not found.')
            name=safe_name(changes.get('name',e['name']))
            if any(x['spectrum_id']!=sid and x['name'].casefold()==name.casefold() and not x['archived'] for x in entries):
                raise ValueError('Another active spectrum has that name.')
            for k in ('category','description','archived'):
                if k in changes:e[k]=changes[k]
            e['name']=name; self.write(entries)
        return e

    def manage_archived(self,ids,action):
        with self.lock:
            records=self.read(True);selected=set(ids)
            if not selected or len(selected)!=len(ids):raise ValueError('Select distinct archived spectra.')
            found=[e for e in records if e['spectrum_id'] in selected]
            if len(found)!=len(selected) or any(not e['archived'] for e in found):raise ValueError('Only archived spectra can be restored or deleted here.')
            if action=='delete':records=[e for e in records if e['spectrum_id'] not in selected]
            elif action=='restore':
                names={e['name'].casefold() for e in records if not e['archived']}
                for e in found:
                    if e['name'].casefold() in names:raise ValueError('An active spectrum already uses '+e['name']+'. Rename the archived entry before restoring.')
                    names.add(e['name'].casefold());e['archived']=False
            else:raise ValueError('Unknown archived action.')
            self.write(records)
            return {'updated':len(found)}

def helmet_mask(w):
    return ((w>=922.5)&(w<=989))|((w>=1085.5)&(w<=1197.5))|((w>=1334)&(w<=1500))|(w>=1750)

def apply_mask(w,values,settings):
    v=np.asarray(values,float).copy();mask=~np.isfinite(v)
    if settings.get('bad_ranges'):mask |= excluded(w,settings['bad_ranges'])
    if settings.get('preset')=='helmet':mask|=helmet_mask(w)
    for part in settings.get('exclusions','').split(','):
        if not part.strip():continue
        try:lo,hi=map(float,part.split(':'))
        except ValueError:raise ValueError('Use exclusions such as 1350:1450,1800:1950 in nm.')
        if not np.isfinite([lo,hi]).all() or lo>hi:raise ValueError('Invalid exclusion range.')
        mask|=(w>=lo)&(w<=hi)
    if settings.get('wavelength_min') is not None:mask |= w < float(settings['wavelength_min'])
    if settings.get('wavelength_max') is not None:mask |= w > float(settings['wavelength_max'])
    v[mask]=np.nan;return v

def align(entry,w,allow=False,method=None):
    source=np.array(entry['wavelengths'],float);values=vector(entry)
    if len(source)==len(w) and np.allclose(source,w,rtol=0,atol=1e-6):return values
    if not allow:raise ValueError('Band centers differ. Enable overlap resampling to compare compatible wavelength coverage.')
    return resample_spectrum(source,values,w,method=method,excluded_ranges=[])[1]


def prepare(entry,settings):
    w=np.array(entry['wavelengths'],float)
    if not settings.get('target_grid'):return entry
    # Apply source validity exclusions before fitting a spline; range bounds
    # restrict evaluated output, not the interpolation support at the boundary.
    source_settings={k:v for k,v in settings.items() if k not in ('wavelength_min','wavelength_max')}
    values=apply_mask(w,vector(entry),source_settings)
    ranges=list(settings.get('bad_ranges',[]))
    for part in settings.get('exclusions','').split(','):
        if part.strip():ranges.append(list(map(float,part.split(':'))))
    w,v=resample_spectrum(w,values,settings['target_grid'],settings.get('interpolation'),ranges,settings.get('max_gap_factor',3))
    return {**entry,'wavelengths':w.tolist(),'values':clean(apply_mask(w,v,settings))}


def aligned_inputs(target,candidates,settings):
    if settings.get("fit_grid")=="target":settings={**settings,"target_grid":target["wavelengths"],"resample":True}
    if settings.get('target_grid'):
        target=prepare(target,settings);candidates=[prepare(e,settings) for e in candidates]
    w=np.array(target['wavelengths'],float)
    y=apply_mask(w,vector(target),settings)
    if not candidates:raise ValueError('Select at least one candidate from the library.')
    if len(candidates)>100:raise ValueError('Select at most 100 candidates.')
    columns=[]
    for e in candidates:
        source_w=np.array(e['wavelengths'],float)
        masked={**e,'values':clean(apply_mask(source_w,vector(e),settings))}
        columns.append(apply_mask(w,align(masked,w,settings.get('resample',False),settings.get('interpolation')),settings))
    A=np.array(columns).T
    valid=np.isfinite(y)&np.isfinite(A).all(axis=1)
    return w,y,A,valid

def matrix(target,candidates,settings):
    w,y,A,valid=aligned_inputs(target,candidates,settings)
    if valid.sum()<max(3,len(candidates)):raise ValueError('Too few shared valid bands. Review candidates, coverage, and exclusions.')
    if np.linalg.norm(y[valid])==0 or np.any(np.linalg.norm(A[valid],axis=0)==0):raise ValueError('A spectrum has no signal on the shared valid bands.')
    return w,y,A,valid

def alignment_preview(target,candidates,settings):
    w,y,A,valid=aligned_inputs(target,candidates,settings)
    target_valid=np.isfinite(y);count=int(target_valid.sum())
    rows=[]
    for i,e in enumerate(candidates):
        overlap=target_valid & np.isfinite(A[:,i]);n=int(overlap.sum())
        rows.append(dict(id=e['spectrum_id'],name=e['name'],source_bands=len(e['wavelengths']),overlap_bands=n,coverage=n/count if count else 0,limited=n<count))
    reasons=['usable' if valid[i] else 'target excluded' if not target_valid[i] else 'candidate unavailable' for i in range(len(w))]
    enough=int(valid.sum())>=max(3,len(candidates))
    signal=bool(valid.any() and np.linalg.norm(y[valid])>0 and np.all(np.linalg.norm(A[valid],axis=0)>0))
    return dict(target_bands=len(target['wavelengths']),analysis_bands=len(w),target_valid_bands=count,used_bands=int(valid.sum()),wavelengths=w.tolist(),status=reasons,candidates=rows,can_fit=enough and signal,message='' if enough and signal else 'Too few shared valid bands or zero signal. Review candidates and exclusions.')

def fit(target,candidates,settings,*,aligned=None,diagnostics=True):
    w,y,A,valid=matrix(target,candidates,settings) if aligned is None else aligned;X=A[valid];t=y[valid]
    mode=settings.get('mode','sparse');warnings=[]
    if mode=='sparse':
        a,alpha,ok,iterations=sparse_fit(X,t,float(settings.get('strength',.001)))
        if not ok:raise ValueError('Sparse solver did not converge. Reduce redundant candidates or change sparsity.')
    elif mode=='fractions':
        def solve(B):
            # Relative objective scale improves the optimizer for low-reflectance targets.
            scale=max(np.mean(t*t),1e-12)
            fun=lambda a:np.mean((B@a-t)**2)/scale
            jac=lambda a:2*B.T@(B@a-t)/len(t)/scale
            result=minimize(fun,np.ones(B.shape[1])/B.shape[1],jac=jac,bounds=[(0,1)]*B.shape[1],constraints={'type':'eq','fun':lambda a:a.sum()-1,'jac':lambda a:np.ones(len(a))},method='SLSQP',options={'maxiter':3000,'ftol':1e-12})
            if not result.success:raise ValueError('Fraction fit did not converge: '+result.message)
            return result.x
        a=solve(X);alpha=0;iterations=None
        k=int(settings.get('max_materials',0))
        if k<0:raise ValueError('Maximum materials cannot be negative.')
        if 0<k<len(a):
            indices=np.argsort(a)[-k:];small=solve(X[:,indices]);a=np.zeros(len(a));a[indices]=small
            warnings.append('Maximum-material selection uses a prune-and-refit heuristic, not an exhaustive subset search.')
    else:raise ValueError('Unknown fitting mode.')
    Xn=X/np.linalg.norm(X,axis=0)
    if diagnostics and len(a)>1 and np.max(Xn.T@Xn-np.eye(len(a)))>.995:warnings.append('Very similar candidates: individual abundances may be ambiguous.')
    if diagnostics and np.linalg.matrix_rank(X)<len(a):warnings.append('Linearly dependent candidates; coefficients may not be unique.')
    pred=X@a;res=t-pred;full=np.full(len(w),np.nan);full[valid]=pred
    if not np.any(a>1e-8):warnings.append('No active coefficients. Lower sparsity or choose other candidates.')
    return dict(wavelengths=w.tolist(),values=clean(full),name='Reconstruction',coefficients=[dict(id=e['spectrum_id'],name=e['name'],color=e.get('color'),value=float(v)) for e,v in zip(candidates,a)],coefficient_sum=float(a.sum()),rmse=float(np.sqrt(np.mean(res**2))),relative_error=float(np.linalg.norm(res)/np.linalg.norm(t)),used_bands=int(valid.sum()),excluded_bands=int((~valid).sum()),warnings=warnings,mode=mode,alpha=alpha)

def compare(target,candidates,settings):
    results=[]
    # Use a common band intersection so every ranked score has the same basis.
    w,y,A,valid=matrix(target,candidates,settings)
    t=y[valid]
    for j,e in enumerate(candidates):
        x=A[valid,j];cos=float(np.clip(x@t/(np.linalg.norm(x)*np.linalg.norm(t)),-1,1))
        results.append(dict(id=e['spectrum_id'],name=e['name'],color=e.get('color'),cosine=cos,angle=float(np.degrees(np.arccos(cos))),rmse=float(np.sqrt(np.mean((x-t)**2))),bands=int(valid.sum())))
    return sorted(results,key=lambda x:x['rmse'] if settings.get('rank')=='rmse' else x['angle'])

def mixture(candidates,weights,settings):
    if not candidates or len(weights)!=len(candidates):raise ValueError('Choose materials and fractions.')
    weights=np.asarray(weights,float)
    if not np.isfinite(weights).all() or (weights<0).any() or abs(weights.sum()-1)>1e-6:raise ValueError('Mixture fractions must total 100%.')
    w,y,A,valid=matrix(candidates[0],candidates,settings)
    v=np.full(len(w),np.nan);v[valid]=A[valid]@weights
    noise=float(settings.get('noise',0))
    if not np.isfinite(noise) or not 0<=noise<=.2:raise ValueError('Noise standard deviation must be between 0 and 0.2.')
    noisy=v.copy();noisy[valid]+=np.random.default_rng(int(settings.get('seed',42))).normal(0,noise,int(valid.sum()))
    return dict(name='Synthetic mixture',wavelengths=w.tolist(),values=clean(noisy),clean_values=clean(v),used_bands=int(valid.sum()),source='Synthetic experiment',category='Mixtures',description=f'Synthetic mixture; noise standard deviation {noise}; seed {settings.get("seed",42)}.')

LEGACY_GRID_NM = np.array([0.4455, 0.4615, 0.4775, 0.4935, 0.5095, 0.5255, 0.5415, 0.5575, 0.5735, 0.5895, 0.6055, 0.6215, 0.6375, 0.6535, 0.6695, 0.6855, 0.7015, 0.7175, 0.7335, 0.7495, 0.7655, 0.7815, 0.7975, 0.8135, 0.8295, 0.8455, 0.8615, 0.8775, 0.8935, 0.9095, 0.9255, 0.9415, 0.9575, 0.9735, 0.9895, 1.0055, 1.0215, 1.0375, 1.0535, 1.0695, 1.0855, 1.1015, 1.1175, 1.1335, 1.1495, 1.1655, 1.1815, 1.1975, 1.2135, 1.2295, 1.2455, 1.2615, 1.2775, 1.2935, 1.3095, 1.3255, 1.4695, 1.4855, 1.5015, 1.5175, 1.5335, 1.5495, 1.5655, 1.5815, 1.5975, 1.6135, 1.6295, 1.6455, 1.6615, 1.6775, 1.6935, 1.7095, 1.7255, 1.7415, 1.7575, 1.7735, 1.7895, 1.9815, 1.9975, 2.0135]) * 1000

def parse_csv(text,filename,unit='auto'):
    """Read HELMET long/wide libraries or two-column spectra; preserve native grid."""
    if unit not in ('auto','nm','um'):raise ValueError('Choose automatic units, nm, or µm.')
    factor=1000 if unit=='um' else 1
    rows=[row for row in csv.reader(io.StringIO(text.lstrip('\ufeff'))) if any(cell.strip() for cell in row)]
    if not rows:raise ValueError('Empty CSV file.')
    header=[cell.strip() for cell in rows[0]];rows[0]=header;entries=[]
    if 'band_center_nm' in header and ('spectrum_id' in header or 'spectrum' in header):
        groups={}
        for row in (dict(zip(header,row)) for row in rows[1:]):
            sid=row.get('spectrum_id',row.get('spectrum'))
            if row.get('archived','0').lower() in ('1','true'):continue
            if sid not in groups:groups[sid]=dict(name=row.get('name',row.get('spectrum',filename)),category=row.get('category','Imported'),description=row.get('description',''),source=filename,source_id=row.get('source_id',''),contributors=json.loads(row.get('contributors') or '[]'),standard_deviation=[],wavelengths=[],values=[])
            e=groups[sid];e['standard_deviation'].append(float(row['standard_deviation']) if row.get('standard_deviation') else None);e['wavelengths'].append(float(row['band_center_nm']));e['values'].append(float(row['reflectance']) if row.get('valid','1')=='1' and row['reflectance'] else None)
        entries=list(groups.values())
    elif 'Material' in header:
        bands=[]
        for i,h in enumerate(header):
            try:bands.append((i,float(h)))
            except ValueError:pass
        if len(bands)<3:raise ValueError('The library needs at least three wavelength-named columns.')
        detected_unit = ('um' if max(w for _,w in bands)<50 else 'nm') if unit=='auto' else unit
        factor=1000 if detected_unit=='um' else 1
        bands=sorted((i,w*factor) for i,w in bands)
        bands.sort(key=lambda item:item[1])
        wavelengths=np.array([w for _,w in bands])
        legacy=len(wavelengths)==len(LEGACY_GRID_NM) and np.allclose(wavelengths,LEGACY_GRID_NM,rtol=0,atol=1e-5)
        for line,row in enumerate(rows[1:],2):
            field=lambda name,default='': row[header.index(name)].strip() if name in header and header.index(name)<len(row) else default
            name=field('Material')
            if not name:raise ValueError(f'Library row {line} contains data but has no material name.')
            values=[]
            for i,w in bands:
                token=row[i].strip() if i<len(row) else ''
                if token.lower() in ('','nan','na','n/a','null','none'):v=None
                else:
                    try:v=float(token)
                    except ValueError:raise ValueError(f'{name}: invalid reflectance {token!r} at {w:g} nm.')
                    if not np.isfinite(v):v=None
                values.append(v)
            if legacy:
                values=[None if masked else v for v,masked in zip(values,helmet_mask(wavelengths))]
            note=f'Wavelengths read as {detected_unit}; stored in nm.'
            if legacy:note+=' Recognized the legacy HELMET grid; its bad-band mask is applied.'
            entries.append(dict(name=name,category=field('Category','Imported'),description=field('Description'),source=filename,source_id=field('ID'),wavelengths=wavelengths.tolist(),values=values,import_note=note))
    else:
        pairs=[]
        for row in rows:
            if len(row)<2:continue
            try:w=float(row[0])*factor
            except ValueError:continue
            try:v=float(row[1]) if row[1].strip() else np.nan
            except ValueError:v=np.nan
            pairs.append((w,v))
        pairs.sort()
        if unit=='auto' and pairs and max(w for w,_ in pairs)<50:pairs=[(w*1000,v) for w,v in pairs]
        entries=[dict(name=Path(filename).stem,category='Imported',description='Imported spectrum; units confirmed by user.',source=filename,wavelengths=[w for w,_ in pairs],values=clean([v for _,v in pairs]))]
    for e in entries:validate(e);e['values']=clean(vector(e))
    if not entries:raise ValueError('No active spectra found in this file.')
    return entries
