#!/usr/bin/env python3
"""HELMET unified local workbench. Run: python3 app.py"""
import argparse, io, json, threading, shutil
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from PIL import Image
from cube_reader import Cube, parse_envi_header, nearest_bands
from region import region_average
from scene_unmix import unmix_batch
from fast_unmix import backend_info, source_fingerprint
from unmix_jobs import RunManager
from unmix_export import export_rectangle
from engine import alignment_preview
from material_analysis import Preferences, settings_for, average, rank, duplicates
from resampling import configuration
from engine import prepare, Store, clean, vector, align, apply_mask, fit, compare, mixture, parse_csv

ROOT=Path(__file__).resolve().parent
class Workspace:
    def __init__(self,library,path=None):
        self.lock=threading.RLock();self.version=0
        self.store=Store(library,[])
        self.preferences=Preferences(library)
        self.runs=RunManager(Path(library).resolve().parent/'.helmet'/Path(library).stem)
        self.cube=None;self.cache={}
        if path:self.open(path)
    def open(self,path):
        p=Path(path).expanduser().resolve()
        if not p.is_file():raise ValueError('Image file was not found. Enter its full local path.')
        headers=[p.with_suffix('.hdr'),Path(str(p)+'.hdr')]
        hp=next((h for h in headers if h.exists()),None)
        if hp is None:raise ValueError('Place a matching .hdr or .img.hdr file beside the image.')
        h=parse_envi_header(str(hp))
        if not h or min(h.get('bands',0),h.get('lines',0),h.get('samples',0))<=0:raise ValueError('Header needs valid bands, lines, and samples.')
        if not h.get('wavelength') or len(h['wavelength'])!=h['bands']:raise ValueError('Header must include one wavelength center per band.')
        wl=np.array(h['wavelength'],float)
        if not np.isfinite(wl).all() or np.any(np.diff(wl)<=0):raise ValueError('Wavelengths must be finite, unique, and increasing.')
        cube=Cube(str(p),h['bands'],h['lines'],h['samples'],h['dtype'],h['interleave'],h.get('scale') or 1,wl[0],wl[-1],wavelengths=wl,bbl=h.get('bbl'),nodata=h.get('nodata'),offset=h.get('offset',0))
        self.cube=cube;self.cube_fingerprint=source_fingerprint(cube);self.version+=1;self.cache={};self.scale_inferred=h.get('scale') is None
    def meta(self):
        if self.cube is None:return None
        c=self.cube
        return dict(name=Path(c.path).name,rows=c.nr,cols=c.nc,bands=c.nb,masked=int(c.masked.sum()),wl_min=float(c.wl[0]),wl_max=float(c.wl[-1]),version=self.version,scale=c.scale,scale_inferred=self.scale_inferred)
    def pixel(self,r,c):
        if self.cube is None:raise ValueError('Open a dataset first.')
        cube=self.cube
        if type(r)is not int or type(c)is not int or not(0<=r<cube.nr and 0<=c<cube.nc):raise ValueError('Pixel coordinates are outside this cube.')
        v=cube.pixel_spectrum(r,c);v[cube.masked]=np.nan
        if cube.nodata is not None:v[cube.data[:,r,c]==cube.nodata]=np.nan
        return dict(name=f'Pixel {r}, {c}',row=r,column=c,source=f'{Path(cube.path).name} · row {r}, column {c}',category='Scene samples',description='Saved from the active cube.',wavelengths=cube.wl.tolist(),values=clean(v))
    def target(self,d):
        if d.get('target')=='pixel':return self.pixel(d.get('row'),d.get('column'))
        if isinstance(d.get('target'),dict):
            from engine import validate
            return validate(d['target'])
        e=next((e for e in self.store.read() if e['spectrum_id']==d.get('target')),None)
        if not e:raise ValueError('Choose a target spectrum.')
        return e
    def candidates(self,ids):
        if not ids or len(ids)!=len(set(ids)):raise ValueError('Choose distinct library candidates.')
        library={e['spectrum_id']:e for e in self.store.read()}
        if any(i not in library for i in ids):raise ValueError('A candidate is no longer available.')
        return [library[i] for i in ids]
    def rgb(self,palette):
        if self.cube is None:raise ValueError('Open a dataset first.')
        if palette in self.cache:return self.cache[palette]
        c=self.cube;targets=[660,550,480] if palette=='true' else [850,660,550]
        arrays=[]
        for b in nearest_bands(c.wl,targets):
            arr=c.data[b].astype(float);valid=np.isfinite(arr)
            if c.nodata is not None:valid&=arr!=c.nodata
            lo,hi=np.percentile(arr[valid],[2,98]) if valid.any() else (0,1)
            arrays.append(np.where(valid,np.clip((arr-lo)/max(hi-lo,1e-10),0,1)*255,0).astype('uint8'))
        stream=io.BytesIO();Image.fromarray(np.stack(arrays,axis=-1)).save(stream,format='PNG');self.cache[palette]=stream.getvalue();return self.cache[palette]
    def scores(self,d):
        c=self.cube;target=self.target(d);settings=d.get('settings',{})
        w=np.array(target['wavelengths']);target={**target,'values':clean(apply_mask(w,vector(target),settings))}
        if settings.get('target_grid'):
            ref=vector(prepare(target,{**settings,'target_grid':c.wl.tolist()}))
        else:ref=apply_mask(c.wl,align(target,c.wl,settings.get('resample',False),settings.get('interpolation')),settings)
        valid=(~c.masked)&np.isfinite(ref)
        if valid.sum()<3 or np.linalg.norm(ref[valid])==0:raise ValueError('Reference has insufficient valid overlapping bands.')
        ref=ref[valid];out=np.full((c.nr,c.nc),np.nan,np.float32)
        for start in range(0,c.nr,24):
            raw=c.data[valid,start:start+24].astype(float);block=raw/c.scale;norms=np.linalg.norm(block,axis=0)
            good=np.isfinite(block).all(axis=0)&(norms>0)
            if c.nodata is not None:good&=(raw!=c.nodata).all(axis=0)
            dots=np.einsum('b,brc->rc',ref,block);np.divide(dots,norms*np.linalg.norm(ref),out=dots,where=good)
            out[start:start+24]=np.where(good,np.clip(dots,-1,1),np.nan)
        return out.astype('<f4').tobytes()

class Handler(BaseHTTPRequestHandler):
    workspace=None
    def log_message(self,*args):pass
    def send(self,body,kind='application/json',status=200,headers=None):
        if not isinstance(body,bytes):body=json.dumps(body,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        p=urlparse(self.path);q=parse_qs(p.query);w=self.workspace
        try:
            if p.path=='/api/unmix/backends':return self.send(backend_info())
            if p.path=='/api/unmix/runs':return self.send(w.runs.list())
            if p.path=='/api/unmix/status':return self.send(w.runs.status(q.get('id',[''])[0],int(q.get('after',['0'])[0]),int(q.get('limit',['2048'])[0])))
            with w.lock:
                if p.path=='/api/analysis/config':return self.send({'defaults':configuration(),**w.preferences.read()})
                if p.path=='/api/meta':return self.send(w.meta())
                if p.path=='/api/library':return self.send({'entries':w.store.read(True),'path':str(w.store.path)})
                if p.path=='/api/pixel':return self.send(w.pixel(int(q.get('row',['0'])[0]),int(q.get('column',['0'])[0])))
                if p.path=='/api/rgb':return self.send(w.rgb(q.get('palette',['false'])[0]),'image/png')
                if p.path=='/api/library.csv':return self.send(w.store.to_csv(w.store.read()).encode(),'text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="HELMET-library.csv"'})
            files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/region.js':('region.js','text/javascript'),'/workflow.js':('workflow.js','text/javascript'),'/unmix.js':('unmix.js','text/javascript'),'/unmix_geometry.js':('unmix_geometry.js','text/javascript'),'/unmix_viewer.js':('unmix_viewer.js','text/javascript'),'/materials.js':('materials.js','text/javascript'),'/style.css':('style.css','text/css')}
            if p.path in files:
                name,kind=files[p.path];return self.send((ROOT/'static'/name).read_bytes(),kind+'; charset=utf-8')
            self.send({'error':'Not found'},status=404)
        except (ValueError,KeyError) as e:self.send({'error':str(e)},status=400)
        except Exception as e:self.send({'error':str(e)},status=500)
    def do_POST(self):
        try:
            if self.headers.get('Origin') and self.headers['Origin']!='http://'+self.headers.get('Host',''):return self.send({'error':'Cross-origin request rejected'},status=403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Expected JSON.')
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<=20_000_000:raise ValueError('Request must be smaller than 20 MB.')
            d=json.loads(self.rfile.read(length));w=self.workspace
            with w.lock:
                if self.path=='/api/unmix/start':
                    if w.cube is None:raise ValueError('Open a dataset first.')
                    if d.get('version')!=w.version:raise ValueError('Dataset changed. Start again.')
                    if source_fingerprint(w.cube)!=w.cube_fingerprint:raise ValueError('The source files changed. Reopen the dataset before running.')
                    return self.send(w.runs.start(w.cube,w.meta(),w.candidates(d['ids']),d['settings'],d.get('accuracy','balanced'),d.get('device','auto'),d.get('retry',True),float(d.get('ceiling',.1)),d.get('bounds'),d.get('preview',False)))
                if self.path=='/api/unmix/pause':return self.send(w.runs.pause(d['id']))
                if self.path in ('/api/unmix/load','/api/unmix/resume'):
                    record=w.runs.info(d['id']);source=record['source']
                    if not Path(source['path']).is_file() or source_fingerprint(source['path'])!=source:raise ValueError('The saved source image or header is missing or changed. Start a new analysis.')
                    if w.cube is None or w.cube_fingerprint!=source:
                        w.open(source['path'])
                    if source_fingerprint(w.cube)!=source:raise ValueError('The source image or header changed. Start a new analysis.')
                    if self.path=='/api/unmix/resume':record=w.runs.resume(w.cube,d['id'])
                    return self.send({**record,'meta':w.meta()})
                if self.path in ('/api/fit/scene','/api/region/export','/api/region/average','/api/scores') and w.cube is None:raise ValueError('Open a dataset first.')
                if self.path=='/api/region/export':
                    if d.get('version')!=w.version:raise ValueError('Dataset changed. Select the region again.')
                    with export_rectangle(w.cube,w.rgb(d.get('palette','false')),d) as archive:
                        archive.seek(0,2);size=archive.tell();archive.seek(0)
                        self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(size));self.send_header('Content-Disposition','attachment; filename=HELMET-region.zip');self.send_header('Cache-Control','no-store');self.end_headers()
                        shutil.copyfileobj(archive,self.wfile)
                    return
                if self.path=='/api/categories':result=w.preferences.category(d['name'])
                elif self.path=='/api/presets':result=w.preferences.preset(d['name'],d['settings'])
                elif self.path=='/api/library/category':
                    category=d['category'];w.preferences.category(category)
                    records=w.store.read(True);ids=set(d['ids'])
                    if not ids.issubset({e['spectrum_id'] for e in records}):raise ValueError('A spectrum was not found.')
                    for e in records:
                        if e['spectrum_id'] in ids:e['category']=category
                    w.store.write(records);result={'updated':len(ids)}
                elif self.path=='/api/average':result=average(w.candidates(d['ids']),settings_for(d.get('settings',{})))
                elif self.path=='/api/materials/preview':result=prepare(w.target(d),settings_for(d.get('settings',{})))
                elif self.path=='/api/materials/matches':
                    target=w.target(d);candidates=w.candidates(d['ids'])
                    candidates=[e for e in candidates if e['spectrum_id']!=target.get('spectrum_id')]
                    result=rank(target,candidates,settings_for(d.get('settings',{})))
                elif self.path=='/api/duplicates':result=duplicates(w.candidates(d['ids']),settings_for(d.get('settings',{})),float(d.get('threshold',.995)),None if d.get('max_rmse') is None else float(d['max_rmse']))
                elif self.path=='/api/open':w.open(d['path']);result=w.meta()
                elif self.path=='/api/library/save':
                    e=w.target(d);e={**e,'name':d['name'],'category':d.get('category',e.get('category','Custom')),'description':d.get('description',e.get('description',''))};result=w.store.save(e)
                elif self.path=='/api/library/archived':
                    if d.get('action')=='delete' and d.get('confirmation')!='DELETE':raise ValueError('Confirm permanent deletion.')
                    result=w.store.manage_archived(d['ids'],d['action'])
                elif self.path=='/api/library/update':result=w.store.update(d['id'],d['changes'])
                elif self.path=='/api/import/preview':result={'entries':parse_csv(d['text'],d['filename'],d.get('unit','auto'))}
                elif self.path=='/api/import/save':
                    result={'saved':[],'errors':[]}
                    for e in d['entries']:
                        try:result['saved'].append(w.store.save(e)['name'])
                        except ValueError as error:result['errors'].append({'name':e.get('name','Unknown'),'error':str(error)})
                elif self.path=='/api/region/average':
                    if d.get('version')!=w.version:raise ValueError('Dataset changed. Select the region again.')
                    result=region_average(w.cube,d['bounds'])
                elif self.path=='/api/fit/preview':result=alignment_preview(w.target(d),w.candidates(d['ids']),d.get('settings',{}))
                elif self.path=='/api/fit/scene':
                    if d.get('version')!=w.version:raise ValueError('Dataset changed. Run scene unmixing again.')
                    result=unmix_batch(w.cube,w.candidates(d['ids']),d.get('settings',{}),d.get('start'),d.get('count',64),d.get('retry',True),float(d.get('ceiling',.1)))
                elif self.path=='/api/fit':result=fit(w.target(d),w.candidates(d['ids']),d.get('settings',{}))
                elif self.path=='/api/compare':result=compare(w.target(d),w.candidates(d['ids']),d.get('settings',{}))
                elif self.path=='/api/mix':result=mixture(w.candidates(d['ids']),d['weights'],d.get('settings',{}))
                elif self.path=='/api/scores':return self.send(w.scores(d),'application/octet-stream')
                else:return self.send({'error':'Not found'},status=404)
            self.send(result)
        except (ValueError,KeyError,TypeError) as e:self.send({'error':str(e)},status=400)
        except Exception as e:self.send({'error':str(e)},status=500)

def main():
    p=argparse.ArgumentParser();p.add_argument('--path',default=None);p.add_argument('--library',default=str(ROOT/'data/spectral_library.csv'));p.add_argument('--port',type=int,default=8766);a=p.parse_args()
    Handler.workspace=Workspace(a.library,a.path)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    print(f'HELMET ready: http://127.0.0.1:{a.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()
    finally:Handler.workspace.runs.close()
if __name__=='__main__':main()
