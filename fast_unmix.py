"""Tiled spectral preparation and batched nonnegative sparse regression.

The sparse objective and per-pixel alpha match engine.sparse_fit. Grouping by
validity mask permits shared Gram matrices without mixing missing measurements.
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator
from engine import aligned_inputs, apply_mask, clean, fit
from resampling import excluded

PROFILES = {'fast': (1e-5, 2000), 'balanced': (1e-7, 6000), 'precise': (1e-9, 20000)}
TILE_SIZE = 2048
CACHE_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def source_fingerprint(cube):
    path = Path(getattr(cube,'path',cube)).resolve()
    stat = path.stat()
    headers = [path.with_suffix('.hdr'), Path(str(path)+'.hdr')]
    header = next((p for p in headers if p.exists()), None)
    return dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                header_sha256=hashlib.sha256(header.read_bytes()).hexdigest() if header else None)


def spectral_settings(cube, settings):
    keys = ('target_grid','bad_ranges','interpolation','max_gap_factor','preset','resample','exclusions','wavelength_min','wavelength_max')
    result = {k: settings[k] for k in keys if k in settings}
    if settings.get('fit_grid') == 'target':
        result.update(target_grid=cube.wl.tolist(), resample=True)
    return result


def resample_tile(cube, indices, settings):
    """Native pixels stay intact; interpolate all pixels sharing a mask at once."""
    raw = cube.data[:, indices//cube.nc, indices%cube.nc].astype(np.float64)
    values = raw/cube.scale
    values[cube.masked] = np.nan
    if cube.nodata is not None:
        values[raw == cube.nodata] = np.nan
    source_settings = {k:v for k,v in settings.items() if k not in ('wavelength_min','wavelength_max')}
    if not settings.get('target_grid'):
        values[~np.isfinite(apply_mask(cube.wl, np.ones(len(cube.wl)), settings))] = np.nan
        return values
    values[~np.isfinite(apply_mask(cube.wl, np.ones(len(cube.wl)), source_settings))] = np.nan
    target = np.asarray(settings['target_grid'], float)
    if target.ndim != 1 or len(target)<2 or not np.isfinite(target).all() or np.any(np.diff(target)<=0):
        raise ValueError('Target wavelengths must be finite and increasing.')
    if np.array_equal(target, cube.wl):
        out = values
    else:
        method = settings.get('interpolation') or 'cubic_spline'
        if method not in ('linear','cubic_spline','pchip'):
            raise ValueError('Unknown interpolation method.')
        gap = settings.get('max_gap_factor',3)
        if not np.isfinite(gap) or gap<=0:raise ValueError('Invalid interpolation gap factor.')
        ranges = list(settings.get('bad_ranges', []))
        ranges += [list(map(float,p.split(':'))) for p in settings.get('exclusions','').split(',') if p.strip()]
        out = np.full((len(target), len(indices)), np.nan)
        _, first, inverse = np.unique(np.packbits(np.isfinite(values),axis=0).T,axis=0,return_index=True,return_inverse=True)
        masks=np.isfinite(values[:,first]).T
        spacing = np.median(np.diff(cube.wl))
        for group, mask in enumerate(masks):
            pixels = np.flatnonzero(inverse == group)
            bands = np.flatnonzero(mask)
            if not len(bands):continue
            split = [0]
            for j in range(1,len(bands)):
                previous, current = cube.wl[bands[j-1]], cube.wl[bands[j]]
                if bands[j]!=bands[j-1]+1 or current-previous>spacing*gap or any(previous <= (np.inf if hi is None else hi) and current>=lo for lo,hi in ranges):
                    split.append(j)
            split.append(len(bands))
            for begin,end in zip(split[:-1],split[1:]):
                b = bands[begin:end];x=cube.wl[b];y=values[np.ix_(b,pixels)]
                if len(b)==1:
                    inside=np.flatnonzero(np.isclose(target,x[0],rtol=0,atol=1e-6))
                    out[np.ix_(inside,pixels)]=y[0]
                    continue
                inside=np.flatnonzero((target>=x[0]) & (target<=x[-1]))
                if not len(inside):continue
                if method=='linear' or len(b)==2:
                    left=np.clip(np.searchsorted(x,target[inside],side='right')-1,0,len(x)-2)
                    weight=(target[inside]-x[left])/(x[left+1]-x[left])
                    result=y[left]*(1-weight[:,None])+y[left+1]*weight[:,None]
                elif method=='pchip':result=PchipInterpolator(x,y,axis=0,extrapolate=False)(target[inside])
                else:result=CubicSpline(x,y,axis=0,bc_type='natural',extrapolate=False)(target[inside])
                out[np.ix_(inside,pixels)]=result
        out[excluded(target,ranges)] = np.nan
    out[~np.isfinite(apply_mask(target,np.ones(len(target)),settings))] = np.nan
    return out


class TileCache:
    """Bounded RAM LRU plus atomically written, versioned disk tiles."""
    def __init__(self, root=None, memory_bytes=128*1024**2, disk_bytes=2*1024**3):
        self.root=Path(root) if root else None
        self.memory_bytes=memory_bytes;self.disk_bytes=disk_bytes
        self.memory=OrderedDict();self.bytes=0;self.hits=0;self.misses=0
        if self.root:self.root.mkdir(parents=True,exist_ok=True)

    def get(self, cube, settings, indices, fingerprint):
        key=digest(dict(version=CACHE_VERSION,source=fingerprint,settings=settings))
        # Return columns in the caller's order, including a rectangular ROI.
        result=None
        for tile in np.unique(indices//TILE_SIZE):
            positions=np.flatnonzero(indices//TILE_SIZE==tile)
            cache_key=(key,int(tile));path=self.root/key/f'{tile}.npy' if self.root else None
            data=self.memory.pop(cache_key,None)
            if data is not None:self.hits+=1;self.bytes-=data.nbytes
            elif path and path.exists():
                try:
                    data=np.load(path,allow_pickle=False);os.utime(path,None);self.hits+=1
                except (ValueError,OSError):data=None
            if data is None:
                self.misses+=1
                start=int(tile)*TILE_SIZE
                data=resample_tile(cube,np.arange(start,min(cube.nr*cube.nc,start+TILE_SIZE)),settings)
                if path:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    temp=path.with_suffix('.tmp')
                    with temp.open('wb') as stream:np.save(stream,data,allow_pickle=False)
                    os.replace(temp,path)
                    self.trim_disk()
            if data.nbytes<=self.memory_bytes:
                self.memory[cache_key]=data;self.bytes+=data.nbytes
            while self.bytes>self.memory_bytes and self.memory:
                _,array=self.memory.popitem(last=False);self.bytes-=array.nbytes
            if result is None:result=np.empty((data.shape[0],len(indices)))
            result[:,positions]=data[:,indices[positions]-int(tile)*TILE_SIZE]
        return result

    def trim_disk(self):
        files=list(self.root.glob('*/*.npy'))
        sizes=[(p.stat().st_mtime,p,p.stat().st_size) for p in files]
        total=sum(s for _,_,s in sizes)
        for _,path,size in sorted(sizes):
            if total<=self.disk_bytes:break
            path.unlink(missing_ok=True);total-=size


def sparse_cpu(G, B, strength, accuracy='balanced', initial=None, cancel=None):
    tolerance, budget=PROFILES[accuracy]
    n,p=B.shape
    alpha=np.maximum(0,B.max(axis=0))*np.asarray(strength)
    a=np.zeros((n,p)) if initial is None else np.maximum(0,initial.copy())
    limit=tolerance*np.maximum(np.max(np.abs(B),axis=0),1e-12)
    converged=np.zeros(p,dtype=bool);iterations=np.zeros(p,dtype=int)
    active=np.arange(p)
    # Broadcast coordinate updates over the active pixels, never over bands.
    # Keep only unfinished pixels in contiguous working arrays. Fancy-indexing
    # residual[:, active] inside every coordinate update copies and scatters the
    # entire matrix thousands of times for correlated material spectra.
    work=a.copy();rhs=np.ascontiguousarray(B-alpha)
    residual=rhs-G@work
    for iteration in range(budget):
        if cancel is not None and iteration%32==0 and cancel.is_set():raise InterruptedError('Paused')
        for j in range(n):
            delta=np.maximum(0,work[j]+residual[j]/G[j,j])-work[j]
            work[j]+=delta
            residual-=G[:,j,None]*delta[None,:]
        if iteration%32==31:residual=rhs-G@work
        kkt=np.max(np.where(work>0,np.abs(residual),np.maximum(residual,0)),axis=0)
        done=kkt<=limit[active]
        if np.any(done):
            a[:,active[done]]=work[:,done];iterations[active[done]]=iteration+1
            active=active[~done]
            work=np.ascontiguousarray(work[:,~done])
            rhs=np.ascontiguousarray(rhs[:,~done])
            residual=np.ascontiguousarray(residual[:,~done])
        if not len(active):break
    if len(active):a[:,active]=work;iterations[active]=iteration+1
    # Always certify the returned answer using the original double-precision system.
    gradient=G@a-B+alpha
    kkt=np.max(np.where(a>0,np.abs(gradient),np.maximum(-gradient,0)),axis=0)
    converged=kkt<=limit*1.0001
    return a,converged,iterations,kkt


def backend_info():
    try:
        import torch
        devices=['cpu']
        if torch.cuda.is_available():devices.append('cuda')
        if hasattr(torch.backends,'mps') and torch.backends.mps.is_available():devices.append('mps')
        return dict(devices=devices,torch_version=torch.__version__,message='Auto benchmarks CPU and available GPU before choosing. GPU answers are checked on CPU.')
    except (ImportError,OSError) as error:
        return dict(devices=['cpu'],torch_version=None,message='Batched CPU ready. Optional GPU support requires PyTorch (requirements-gpu.txt).')


def sparse_gpu(G,B,strength,accuracy,device,cancel=None):
    """Accelerated projected gradient on GPU, certified/refined on float64 CPU."""
    import torch
    dtype=torch.float32 if device=='mps' else torch.float64
    gram=torch.as_tensor(G,dtype=dtype,device=device)
    b=torch.as_tensor(B,dtype=dtype,device=device)
    alpha=b.max(dim=0).values.clamp(min=0)*torch.as_tensor(np.array(strength,copy=True),dtype=dtype,device=device)
    lipschitz=max(float(np.linalg.eigvalsh(G)[-1]),1e-20)
    a=torch.zeros_like(b);z=a.clone();momentum=1.
    budget=min(PROFILES[accuracy][1],3000)
    for iteration in range(budget):
        if iteration%32==0 and cancel is not None and cancel.is_set():raise InterruptedError('Paused')
        next_a=(z+(b-gram@z-alpha)/lipschitz).clamp(min=0)
        next_momentum=(1+np.sqrt(1+4*momentum*momentum))/2
        z=next_a+(momentum-1)/next_momentum*(next_a-a);a=next_a;momentum=next_momentum
        if iteration%32==31:
            sample=a.detach().cpu().numpy().astype(float)
            gradient=G@sample-B+np.maximum(0,B.max(axis=0))*np.asarray(strength)
            kkt=np.max(np.where(sample>0,np.abs(gradient),np.maximum(-gradient,0)),axis=0)
            if np.all(kkt<=PROFILES[accuracy][0]*np.maximum(np.max(np.abs(B),axis=0),1e-12)):break
    initial=a.detach().cpu().numpy().astype(float)
    answer=sparse_cpu(G,B,strength,accuracy,initial=initial,cancel=cancel)
    answer[2][:]+=iteration+1
    return answer


class BatchedUnmixer:
    def __init__(self,cube,candidates,settings,cache=None,fingerprint=None,accuracy='balanced',device='auto',retry=True,ceiling=.1,cancel=None):
        if accuracy not in PROFILES:raise ValueError('Choose Fast, Balanced, or Precise accuracy.')
        if device not in ('auto','cpu','mps','cuda'):raise ValueError('Unknown processing device.')
        strength=float(settings.get('strength',.001))
        if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError('Sparsity must be between 0 and 1.')
        if retry and settings.get('mode','sparse')=='sparse' and (not np.isfinite(ceiling) or not strength<=ceiling<=1):raise ValueError('Retry ceiling must be between initial sparsity and 1.')
        if settings.get('mode','sparse') not in ('sparse','fractions'):raise ValueError('Unknown fitting mode.')
        self.cube=cube;self.candidates=candidates;self.settings=settings
        self.spectral=spectral_settings(cube,settings)
        self.accuracy=accuracy;self.requested_device=device;self.device='cpu';self.device_message='Batched CPU'
        self.fingerprint=fingerprint or dict(path=str(cube.path),shape=[cube.nr,cube.nc],wavelengths=cube.wl.tolist())
        self.cache=cache or TileCache();self.retry=retry;self.ceiling=ceiling;self.cancel=cancel
        self.grams=OrderedDict();self.calibrated=device=='cpu';self.backend_timings={}
        template=dict(wavelengths=cube.wl.tolist(),values=clean(np.where(cube.masked,np.nan,1.)))
        self.w,_,self.A,shared=aligned_inputs(template,candidates,settings)
        if shared.sum()<max(3,len(candidates)):raise ValueError('Too few shared usable bands for these candidates. Reduce candidates or choose the native target grid.')

    def batch_size(self):
        """Bound working arrays to an estimated 256 MiB per sparse batch.

        Cache chunks remain independent of solver batches. Fractions still uses
        a per-pixel optimizer, so retain shorter checkpoint intervals there.
        """
        if self.settings.get('mode','sparse')=='fractions':return 2048
        bytes_per_pixel=8*(6*len(self.w)+16*len(self.candidates))+1024
        return max(1,min(16384,(256*1024*1024)//bytes_per_pixel))

    def solve(self,G,B,strength):
        if not self.calibrated:
            self.calibrated=True;info=backend_info();available=[v for v in info['devices'] if v!='cpu']
            chosen=self.requested_device if self.requested_device!='auto' else (available[0] if available else 'cpu')
            if chosen not in available:
                self.device_message='CPU fallback: '+info['message'] if chosen!='cpu' or not available else 'Batched CPU'
            else:
                try:
                    # Compare the same representative pixels, including transfer and certification.
                    trial=B[:,:min(512,B.shape[1])];s=np.broadcast_to(strength,(B.shape[1],))[:trial.shape[1]]
                    begin=time.perf_counter();cpu=sparse_cpu(G,trial,s,self.accuracy,cancel=self.cancel);cpu_time=time.perf_counter()-begin
                    begin=time.perf_counter();gpu=sparse_gpu(G,trial,s,self.accuracy,chosen,self.cancel);gpu_time=time.perf_counter()-begin
                    self.backend_timings=dict(cpu_seconds=cpu_time,gpu_seconds=gpu_time,gpu=chosen)
                    if not np.all(gpu[1]>=cpu[1]):raise RuntimeError('GPU certification failed for trial pixels.')
                    if self.requested_device!='auto' or gpu_time<cpu_time*.85:
                        self.device=chosen;self.device_message=chosen.upper()+' with float64 CPU certification'
                    else:self.device_message='CPU selected: faster than '+chosen.upper()+' on the trial tile'
                except InterruptedError:raise
                except Exception as error:self.device_message='CPU fallback: '+str(error)
        if self.device!='cpu':
            try:return sparse_gpu(G,B,strength,self.accuracy,self.device,self.cancel)
            except InterruptedError:raise
            except Exception as error:self.device='cpu';self.device_message='CPU fallback: '+str(error)
        return sparse_cpu(G,B,strength,self.accuracy,cancel=self.cancel)

    def batch(self,indices):
        indices=np.asarray(indices,dtype=int);cube=self.cube
        Y=self.cache.get(cube,self.spectral,indices,self.fingerprint)
        valid=np.isfinite(Y)&np.isfinite(self.A).all(axis=1)[:,None]
        _,first,inverse=np.unique(np.packbits(valid,axis=0).T,axis=0,return_index=True,return_inverse=True)
        masks=valid[:,first].T
        rows=[dict(row=int(i//cube.nc),column=int(i%cube.nc),status='invalid',coefficients=None,rmse=None,relative_error=None,strength=None,attempts=0,used_bands=int(valid[:,j].sum()),iterations=0,kkt=None,message='Insufficient shared bands or zero signal.') for j,i in enumerate(indices)]
        for group,mask in enumerate(masks):
            if self.cancel is not None and self.cancel.is_set():raise InterruptedError('Paused')
            positions=np.flatnonzero(inverse==group)
            if mask.sum()<max(3,len(self.candidates)):continue
            X=self.A[mask];target=Y[np.ix_(mask,positions)]
            nonzero=np.linalg.norm(target,axis=0)>0
            positions=positions[nonzero];target=target[:,nonzero]
            if not len(positions) or np.any(np.linalg.norm(X,axis=0)==0):continue
            if self.settings.get('mode','sparse')=='fractions':
                # Retain the established constrained optimizer and prune/refit policy.
                self.device_message='CPU fractions (SLSQP); cached, batched spectral preparation'
                for j,pos in enumerate(positions):
                    if self.cancel is not None and self.cancel.is_set():raise InterruptedError('Paused')
                    y=Y[:,pos]
                    try:
                        result=fit({},self.candidates,self.settings,aligned=(self.w,y,self.A,mask),diagnostics=False)
                        rows[pos].update(status='ok',coefficients=[v['value'] for v in result['coefficients']],rmse=result['rmse'],relative_error=result['relative_error'],attempts=1,message='; '.join(result['warnings']))
                    except ValueError as error:rows[pos].update(status='failed',attempts=1,message=str(error))
                continue
            key=mask.tobytes()
            if key not in self.grams:
                self.grams[key]=X.T@X/len(X)
                if len(self.grams)>256:self.grams.popitem(last=False)
            G=self.grams[key]
            if np.any(np.diag(G)<=1e-20):
                for pos in positions:rows[pos].update(status='failed',attempts=1,strength=float(self.settings.get('strength',.001)),message='A candidate is zero on the shared valid bands.')
                continue
            B=X.T@target/len(X)
            remaining=np.arange(len(positions));strength=float(self.settings.get('strength',.001))
            while len(remaining):
                a,ok,iterations,kkt=self.solve(G,B[:,remaining],strength)
                residual=target[:,remaining]-X@a
                for j,index in enumerate(remaining):
                    row=rows[positions[index]];row['attempts']+=1;row['strength']=strength;row['iterations']+=int(iterations[j]);row['kkt']=float(kkt[j])
                    if ok[j]:
                        row.update(status='retried' if row['attempts']>1 else 'ok',coefficients=a[:,j].tolist(),rmse=float(np.sqrt(np.mean(residual[:,j]**2))),relative_error=float(np.linalg.norm(residual[:,j])/np.linalg.norm(target[:,index])),message='' if np.any(a[:,j]>1e-8) else 'No active coefficients. Lower sparsity or choose other candidates.')
                    else:row.update(status='failed',message='Sparse solver did not converge at the requested accuracy.')
                remaining=remaining[~ok]
                if not self.retry or strength>=self.ceiling:break
                strength=min(self.ceiling,max(.001,strength*10))
        return rows
