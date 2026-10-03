"""Resumable full-dataset energy/force training with resource-aware process count."""
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
import argparse,json,multiprocessing as mp,signal,time,shutil,copy,fcntl
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import numpy as np
import psutil
import torch
from .adjoint import build_library
from .geometry import ENCODING_VERSION
from .model import EnergyForceModel
from ..data import load_panel,fit_normalizer

ROOT=Path(__file__).resolve().parents[2]
_STOP=False
_WORK={}


def json_save(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False));tmp.replace(path)


def checkpoint(path,state):
    path=Path(path);tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as stream:
        torch.save(state,stream);stream.flush();os.fsync(stream.fileno())
    tmp.replace(path)


def prepare(run):
    run=Path(run);run.mkdir(parents=True,exist_ok=False)
    seed=json.loads((ROOT/'models/initialization/circuit_seed.json').read_text())
    radii=json.loads((ROOT/'models/initialization/radii.json').read_text())
    train=load_panel(include_forces=True);val=load_panel(split='validation',include_forces=True)
    # Fit spatial normalization on the same centered representation used by encoding.
    centered=dict(train);positions=train['positions_angstrom'].copy();mass=np.tile([15.999,1.008,1.008],10)
    positions-=(positions*mass[None,:,None]).sum(1)[:,None,:]/mass.sum()
    centered['positions_angstrom']=positions;normalizer=fit_normalizer(centered)
    force_scale=max(float(np.sqrt(np.mean(train['forces_ev_per_angstrom']**2))),1e-8)
    templates=copy.deepcopy(json.loads((ROOT/'models/final/best_model.json').read_text())['templates'])
    for blocks in templates['encoding'].values():
        for block in blocks:
            for gate in block:gate.pop('encoding_min_abs_angle',None)
    spec=dict(encoding_version=ENCODING_VERSION,templates=templates,theta=seed['theta'],
              normalizer=normalizer,radii=radii,force_scale_ev_per_A=force_scale,seed=916,
              loss='mean normalized energy squared error + mean normalized Cartesian force squared error',
              force_weight=1.,energy_weight=1.,train=3500,validation=500,test_labels_accessed=False)
    json_save(run/'spec.json',spec)
    np.savez(run/'data.npz',positions=np.concatenate([train['positions_angstrom'],val['positions_angstrom']]),
             energies=np.concatenate([train['energy_ev'],val['energy_ev']]),
             forces=np.concatenate([train['forces_ev_per_angstrom'],val['forces_ev_per_angstrom']]),
             sample_ids=np.concatenate([train['sample_id'],val['sample_id']]).astype(str))
    library=build_library(run/'lib');model=EnergyForceModel(spec,library)
    state=dict(spec=spec,model=model.state_dict(),epoch=1,position=0,optimizer=None,
               history=[],best_score=None,bad_epochs=0,updates=0,pending={},batch_indices=[],train_sums=[0.,0.],workers=1)
    checkpoint(run/'latest.pt',state);json_save(run/'initial_model.json',model.export())
    return run


def initialize(run,threads):
    torch.set_num_threads(1);run=Path(run)
    os.environ['WATER10_STOP_FILE']=str(run/'STOP')
    _WORK.update(spec=json.loads((run/'spec.json').read_text()),arrays=np.load(run/'data.npz'),
                 library=str(next((run/'lib').glob('*.so'))),threads=threads)


def task(index,weights,training):
    import resource
    # Four full complex128 arrays are live in HVP; reserve additional working room.
    if psutil.virtual_memory().available<80*2**30:raise MemoryError('Less than 80 GiB available for dense force worker')
    t=time.monotonic();s=_WORK['spec'];a=_WORK['arrays']
    m=EnergyForceModel(s,_WORK['library'],_WORK['threads']);m.load_state_dict(weights)
    x=torch.tensor(a['positions'][index],dtype=torch.float64)
    energy,force=m.energy_forces(x,training=training)
    er=energy-float(a['energies'][index]);fr=force-torch.tensor(a['forces'][index],dtype=torch.float64)
    emse=er.square();fmse=fr.square().mean()
    loss=emse/s['normalizer']['energy_scale_ev']**2+fmse/s['force_scale_ev_per_A']**2
    if training:
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in m.parameters()):raise FloatingPointError('Nonfinite or missing loss gradient')
    return dict(index=index,energy_mse=float(emse.detach()),force_mse=float(fmse.detach()),loss=float(loss.detach()),
                gradients={k:p.grad.detach().clone() for k,p in m.named_parameters()} if training else {},
                seconds=time.monotonic()-t,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)


def resource_cap(threads,peak):
    cpu=len(os.sched_getaffinity(0))
    # Leave 100 GiB available for the OS and other processes, then use the
    # measured per-worker peak with a 40% margin (at least 96 GiB).
    memory=int(max(0,psutil.virtual_memory().available-100*2**30)/max(96*2**30,1.4*peak))
    return max(0,min(cpu//threads,memory))


def train(run,threads=8,batch_size=8,patience=10):
    global _STOP
    run=Path(run)
    def stop_handler(*_):
        globals()['_STOP']=True
        (run/'STOP').write_text('stop requested\n')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop_handler)
    acceptance=json.loads((run/'acceptance.json').read_text())
    if acceptance['status']!='passed':raise RuntimeError('Full-state force acceptance required')
    state=torch.load(run/'latest.pt',weights_only=False,map_location='cpu');spec=state['spec']
    if spec['encoding_version']!=ENCODING_VERSION:raise ValueError('Checkpoint encoding mismatch')
    library=next((run/'lib').glob('*.so'));model=EnergyForceModel(spec,library,threads)
    model.load_state_dict(state['model'])
    opt=torch.optim.Adam([{'params':[model.quantum],'lr':3e-4},{'params':model.classical.parameters(),'lr':1e-3}])
    if state['optimizer'] is not None:opt.load_state_dict(state['optimizer'])
    peak=acceptance['peak_rss_bytes']
    # A single batch can vary substantially with the number of active gates.
    # Retain measurements across restarts and only lower parallelism when a
    # smaller worker count wins repeatedly, by a useful margin.
    speeds=state.setdefault('throughput_by_workers',{})
    if not speeds and (run/'batches.jsonl').exists():
        for line in (run/'batches.jsonl').read_text().splitlines():
            row=json.loads(line)
            speeds.setdefault(str(row['workers']),[]).append(row['samples_per_second'])
    def save():
        state.update(model=model.state_dict(),optimizer=opt.state_dict());checkpoint(run/'latest.pt',state)
    def status(stage,**extra):
        json_save(run/'status.json',dict(stage=stage,epoch=state['epoch'],position=state['position'],updates=state['updates'],workers=state['workers'],time=time.time(),**extra))
    status('training')
    while not _STOP:
        order=np.random.default_rng(spec['seed']+state['epoch']).permutation(spec['train'])
        while state['position']<spec['train'] and not _STOP:
            if (run/'STOP').exists():_STOP=True;break
            if shutil.disk_usage(run).free<5*2**30:status('paused_disk_space');save();return
            cap=resource_cap(threads,peak)
            if cap<1:status('waiting_memory');time.sleep(20);continue
            workers=min(state['workers'],cap,batch_size)
            indices=state.get('batch_indices') or order[state['position']:state['position']+min(batch_size,workers)].tolist()
            state['batch_indices']=indices;save()
            missing=[i for i in indices if str(i) not in state['pending']]
            started=time.monotonic();status('training_batch',batch_indices=indices)
            with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),initializer=initialize,initargs=(str(run),threads)) as pool:
                futures=[pool.submit(task,i,model.state_dict(),True) for i in missing]
                for f in as_completed(futures):
                    row=f.result();peak=max(peak,row['peak_rss_bytes']);state['pending'][str(row['index'])]=row
                    save();status('training_batch',completed_in_batch=len(state['pending']),peak_worker_rss_bytes=peak)
            if len(state['pending'])!=len(indices):raise RuntimeError('Incomplete gradient batch')
            opt.zero_grad(set_to_none=True)
            for name,param in model.named_parameters():param.grad=sum(state['pending'][str(i)]['gradients'][name] for i in indices)/len(indices)
            torch.nn.utils.clip_grad_norm_(model.parameters(),10.,error_if_nonfinite=True);opt.step()
            for i in indices:
                row=state['pending'][str(i)];state['train_sums'][0]+=row['energy_mse'];state['train_sums'][1]+=row['force_mse']
            state['pending']={};state['batch_indices']=[];state['position']+=len(indices);state['updates']+=1
            throughput=len(missing)/max(time.monotonic()-started,1e-9)
            if len(missing)==workers:
                bucket=speeds.setdefault(str(workers),[])
                bucket.append(throughput)
                del bucket[:-5]
            if workers<cap and not any(int(k)>workers for k in speeds):
                state['workers']=min(max(1,workers*2),cap,batch_size)
            else:
                eligible={int(k):sum(v)/len(v) for k,v in speeds.items() if len(v)>=2 and int(k)<=cap}
                baseline=sum(speeds.get(str(workers),[throughput]))/len(speeds.get(str(workers),[throughput]))
                winner=max(eligible,key=eligible.get) if eligible else workers
                state['workers']=winner if winner!=workers and eligible[winner]>1.15*baseline else workers
            save()
            json_save(run/'current_model.json',model.export())
            with (run/'batches.jsonl').open('a') as log:log.write(json.dumps(dict(epoch=state['epoch'],position=state['position'],updates=state['updates'],workers=workers,samples_per_second=throughput,peak_worker_rss_bytes=peak))+'\n')
        if _STOP:break
        status('validation');metrics=[];cap=resource_cap(threads,peak)
        if cap<1:status('waiting_memory');time.sleep(20);continue
        # Validation rows persist independently so an interrupted validation can resume.
        validation_path=run/f'validation_epoch_{state["epoch"]:04d}.json'
        known=json.loads(validation_path.read_text()) if validation_path.exists() else {}
        missing=[i for i in range(spec['train'],spec['train']+spec['validation']) if str(i) not in known]
        with ProcessPoolExecutor(max_workers=min(state['workers'],cap,batch_size),mp_context=mp.get_context('spawn'),initializer=initialize,initargs=(str(run),threads)) as pool:
            for f in as_completed([pool.submit(task,i,model.state_dict(),False) for i in missing]):
                row=f.result();row.pop('gradients');known[str(row['index'])]=row;json_save(validation_path,known)
                status('validation',completed=len(known))
        score=float(np.mean([r['loss'] for r in known.values()]))
        row=dict(epoch=state['epoch'],validation_loss=score,
                 validation_energy_rmse_ev=float(np.sqrt(np.mean([r['energy_mse'] for r in known.values()]))),
                 validation_force_rmse_ev_per_A=float(np.sqrt(np.mean([r['force_mse'] for r in known.values()]))),
                 online_train_energy_rmse_ev=(state['train_sums'][0]/spec['train'])**.5,
                 online_train_force_rmse_ev_per_A=(state['train_sums'][1]/spec['train'])**.5)
        state['history'].append(row);json_save(run/'history.json',state['history'])
        best=state['best_score'];reference=state.get('patience_reference_score')
        significant=reference is None or score<reference-max(1e-6,abs(reference)*1e-4)
        if significant:state['patience_reference_score']=score;state['bad_epochs']=0
        else:state['bad_epochs']+=1
        if best is None or score<best:
            state['best_score']=score
            checkpoint(run/'best.pt',dict(model=model.state_dict(),spec=spec,epoch=state['epoch'],metrics=row))
            json_save(run/'best_model.json',dict(model.export(),epoch=state['epoch'],metrics=row))
        checkpoint(run/f'epoch_{state["epoch"]:04d}.pt',dict(model=model.state_dict(),spec=spec,metrics=row))
        state['epoch']+=1;state['position']=0;state['train_sums']=[0.,0.];save()
        if state['bad_epochs']>=patience:
            status('converged_validation_plateau',criterion=f'{patience} complete validation epochs without relative improvement 1e-4');return
    save();status('stopped_checkpoint_saved')


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','train']);p.add_argument('--run',type=Path,required=True);p.add_argument('--threads',type=int,default=8);a=p.parse_args()
    if a.action=='prepare':prepare(a.run)
    else:
        try:
            with (a.run/'training.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                train(a.run,a.threads)
        except BaseException as error:
            stopped=(a.run/'STOP').exists()
            json_save(a.run/'termination.json',dict(status='stopped_checkpoint_saved' if stopped else 'failed',error=repr(error),time=time.time()))
            if not stopped:raise

if __name__=='__main__':main()
