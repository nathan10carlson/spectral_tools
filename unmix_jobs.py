"""Background runs with atomic SQLite checkpoints and immutable input snapshots."""
from datetime import datetime, timezone
import json
try:
    import fcntl
except ImportError:  # Windows uses the same one-byte worker lock.
    fcntl=None
    import msvcrt
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import numpy as np
from fast_unmix import BatchedUnmixer, TileCache, source_fingerprint, PROFILES

RUN_FORMAT=1


def lock_worker(stream, acquire):
    if fcntl is not None:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)
    else:
        stream.seek(0,2)
        if stream.tell()==0:stream.write('0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK,1)
        except OSError as error:raise BlockingIOError(str(error)) from error


def now():return datetime.now(timezone.utc).isoformat()


def region_bounds(cube,bounds=None):
    if bounds is None:return dict(row_start=0,row_end=cube.nr-1,column_start=0,column_end=cube.nc-1)
    values=[bounds[k] for k in ('row_start','row_end','column_start','column_end')]
    r0,r1,c0,c1=values
    if any(type(v)is not int for v in values) or not (0<=r0<=r1<cube.nr and 0<=c0<=c1<cube.nc):raise ValueError('Choose integer preview bounds inside the image.')
    return dict(bounds)


class RunManager:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.cache=TileCache(self.root/'cache')
        self.worker_lock=(self.root/'worker.lock').open('a+')
        self.lock=threading.RLock();self.thread=None;self.active_id=None;self.cancel=threading.Event()
        # A process exit can interrupt only the current tile; committed pixels survive.
        try:lock_worker(self.worker_lock,True)
        except BlockingIOError:return
        for path in self.root.glob('*/run.sqlite'):
            with sqlite3.connect(path) as db:
                try:
                    record=json.loads(db.execute('SELECT value FROM info WHERE key="run"').fetchone()[0])
                    if record['state']=='running':
                        record.update(state='paused',message='Interrupted by shutdown. Resume from the last checkpoint.')
                        self.write_info(db,record)
                except (sqlite3.Error,ValueError,TypeError):continue
        lock_worker(self.worker_lock,False)

    def close(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():self.thread.join(timeout=10)
        if not self.thread or not self.thread.is_alive():self.worker_lock.close()

    def __del__(self):
        if hasattr(self,'worker_lock'):self.worker_lock.close()

    def path(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{32}',run_id):raise ValueError('Invalid saved run ID.')
        path=self.root/run_id/'run.sqlite'
        if not path.exists():raise ValueError('Saved run was not found.')
        return path

    def connect(self,run_id):
        db=sqlite3.connect(self.path(run_id),timeout=30)
        return db

    @staticmethod
    def write_info(db,record):
        db.execute('INSERT OR REPLACE INTO info VALUES (?,?)',('run',json.dumps(record,allow_nan=False)))

    def info(self,run_id):
        with self.connect(run_id) as db:return json.loads(db.execute('SELECT value FROM info WHERE key="run"').fetchone()[0])

    def list(self):
        records=[]
        for path in self.root.glob('*/run.sqlite'):
            try:
                r=self.info(path.parent.name)
                records.append({**{k:r[k] for k in ('id','label','created','state','done','total','meta','bounds','message')},'removed':r.get('removed',False)})
            except (ValueError,sqlite3.Error,TypeError):continue
        return sorted(records,key=lambda r:r['created'],reverse=True)

    def remove(self,run_id,removed=True):
        if type(removed) is not bool:raise ValueError('Invalid removal setting.')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Pause the current analysis before removing or restoring saved runs.')
            try:lock_worker(self.worker_lock,True)
            except BlockingIOError:raise ValueError('Pause the active analysis before changing saved runs.')
            try:
                record=self.info(run_id)
                record['removed']=removed
                with self.connect(run_id) as db:self.write_info(db,record)
                return record
            finally:lock_worker(self.worker_lock,False)

    def start(self,cube,meta,candidates,settings,accuracy='balanced',device='auto',retry=True,ceiling=.1,bounds=None,preview=False):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Pause the current run before starting another.')
            candidates=json.loads(json.dumps(candidates));settings=json.loads(json.dumps(settings));meta=json.loads(json.dumps(meta))
            bounds=region_bounds(cube,bounds);total=(bounds['row_end']-bounds['row_start']+1)*(bounds['column_end']-bounds['column_start']+1)
            fingerprint=source_fingerprint(cube)
            solver=BatchedUnmixer(cube,candidates,settings,self.cache,fingerprint,accuracy,device,retry,ceiling,self.cancel)
            run_id=uuid.uuid4().hex;folder=self.root/run_id;folder.mkdir()
            record=dict(format_version=RUN_FORMAT,id=run_id,label=('Preview' if preview else 'Scene')+' · '+meta['name'],created=now(),state='paused',message='',done=0,total=total,seconds=0.,counts=dict(ok=0,retried=0,invalid=0,failed=0),meta=meta,source=fingerprint,materials=candidates,settings=settings,accuracy=accuracy,device=device,actual_device='cpu',device_message='Preparing',backend_timings={},retry=dict(enabled=retry,ceiling=ceiling),bounds=bounds,preview=preview,analysis_bands=len(solver.w),iterations=0,cache_hits=0,cache_misses=0)
            with sqlite3.connect(folder/'run.sqlite') as db:
                db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE info (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute('CREATE TABLE pixels (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                self.write_info(db,record)
            self.launch(cube,record,solver)
            return self.info(run_id)

    def save_pixel(self,cube,meta,target,candidates,settings,result):
        """Persist the exact Explore fit, without recomputing it in a batch."""
        row,column=target['row'],target['column']
        bounds=region_bounds(cube,dict(row_start=row,row_end=row,column_start=column,column_end=column))
        run_id=uuid.uuid4().hex;folder=self.root/run_id;folder.mkdir()
        record=dict(format_version=RUN_FORMAT,id=run_id,label=f"Pixel ({row}, {column}) · {meta['name']}",
            kind='pixel',created=now(),state='complete',message='Pixel fit saved.',done=1,total=1,seconds=0.,
            counts=dict(ok=1,retried=0,invalid=0,failed=0),meta=meta,source=source_fingerprint(cube),
            materials=candidates,settings=settings,accuracy='precise',device='cpu',actual_device='cpu',
            device_message='Single-pixel CPU',backend_timings={},retry=dict(enabled=False,ceiling=max(.1,float(settings.get('strength',.001)))),
            bounds=bounds,preview=False,analysis_bands=len(result['wavelengths']),iterations=0,
            cache_hits=0,cache_misses=0,batch_size=1,target=target,fit_result=result)
        pixel=dict(row=row,column=column,pixel_index=row*cube.nc+column,status='ok',
            coefficients=[c['value'] for c in result['coefficients']],rmse=result['rmse'],
            relative_error=result['relative_error'],used_bands=result['used_bands'],
            strength=float(settings.get('strength',.001)),attempts=1,iterations=0,kkt=None,
            message='; '.join(result['warnings']))
        with sqlite3.connect(folder/'run.sqlite') as db:
            db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE info (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE pixels (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            self.write_info(db,record)
            db.execute('INSERT INTO pixels VALUES (?,?)',(0,json.dumps(pixel,allow_nan=False)))
        return run_id

    def launch(self,cube,record,solver=None):
        try:lock_worker(self.worker_lock,True)
        except BlockingIOError:raise ValueError('Another HELMET process is running an analysis for this library.')
        self.cancel.clear();self.active_id=record['id']
        if solver is None:
            solver=BatchedUnmixer(cube,record['materials'],record['settings'],self.cache,record['source'],record['accuracy'],record['device'],record['retry']['enabled'],record['retry']['ceiling'],self.cancel)
        record.update(batch_size=solver.batch_size(),state='running',message='Processing; each finished tile is saved automatically.')
        with self.connect(record['id']) as db:self.write_info(db,record)
        self.thread=threading.Thread(target=self.work,args=(cube,record,solver),daemon=True,name='helmet-unmix')
        self.thread.start()

    def resume(self,cube,run_id):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('A run is already processing. Wait for it to pause.')
            record=self.info(run_id)
            if record.get('removed'):raise ValueError('Restore this analysis before resuming it.')
            if source_fingerprint(cube)!=record['source']:raise ValueError('The source image or header changed. Start a new analysis.')
            if record['format_version']!=RUN_FORMAT:raise ValueError('This checkpoint uses a different solver version. Start a new analysis.')
            if record['done']>=record['total']:return record
            self.launch(cube,record)
            return self.info(run_id)

    def pause(self,run_id):
        with self.lock:
            if run_id==self.active_id and self.thread and self.thread.is_alive():self.cancel.set()
            return self.info(run_id)

    def work(self,cube,record,solver):
        baseline_hits=self.cache.hits;baseline_misses=self.cache.misses
        try:
            b=record['bounds'];width=b['column_end']-b['column_start']+1
            while record['done']<record['total'] and not self.cancel.is_set():
                begin=time.perf_counter();start=record['done'];stop=min(record['total'],start+record['batch_size'])
                seq=np.arange(start,stop);indices=(b['row_start']+seq//width)*cube.nc+b['column_start']+seq%width
                rows=solver.batch(indices)
                updated=json.loads(json.dumps(record))
                with self.connect(record['id']) as db:
                    db.executemany('INSERT INTO pixels VALUES (?,?)',[(start+i,json.dumps(row,allow_nan=False)) for i,row in enumerate(rows)])
                    updated['done']=stop;updated['seconds']+=time.perf_counter()-begin
                    for row in rows:
                        updated['counts'][row['status']]+=1;updated['iterations']+=row.get('iterations',0)
                    updated.update(actual_device=solver.device,device_message=solver.device_message,backend_timings=solver.backend_timings,cache_hits=self.cache.hits-baseline_hits,cache_misses=self.cache.misses-baseline_misses)
                    self.write_info(db,updated)
                record=updated
            record.update(state='complete' if record['done']==record['total'] else 'paused',message='Completed.' if record['done']==record['total'] else 'Paused. Completed tiles are saved.')
        except InterruptedError:record.update(state='paused',message='Paused. The unfinished tile will be recomputed on resume.')
        except Exception as error:record.update(state='error',message=str(error))
        finally:
            try:
                with self.connect(record['id']) as db:self.write_info(db,record)
            finally:lock_worker(self.worker_lock,False)

    def status(self,run_id,after=0,limit=2048):
        if type(after)is not int or after<0 or type(limit)is not int or not 1<=limit<=4096:raise ValueError('Invalid result page.')
        with self.connect(run_id) as db:
            # Metadata and pixel page must come from the same committed checkpoint.
            db.execute('BEGIN')
            record=json.loads(db.execute('SELECT value FROM info WHERE key="run"').fetchone()[0])
            rows=db.execute('SELECT seq,payload FROM pixels WHERE seq>=? ORDER BY seq LIMIT ?',(after,limit)).fetchall()
        progress={k:v for k,v in record.items() if k not in ('source','materials','settings','meta')}
        return dict(run=progress,pixels=[json.loads(row[1]) for row in rows],cursor=rows[-1][0]+1 if rows else after)
