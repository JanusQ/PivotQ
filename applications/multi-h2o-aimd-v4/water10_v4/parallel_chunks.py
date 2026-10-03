"""Balance exact gate-instance shifts across workers, including dense geometries."""
import time,os
from collections import OrderedDict
from concurrent.futures import as_completed
import numpy as np
import psutil
from . import parallel_training as pt
from .circuit import instances


def shift_task(task):
    idx,theta,dz,start,stop=task;work=pt._WORK;sim=work['sim'];before=sim.calls;t0=time.perf_counter()
    cache=work.setdefault('cache',OrderedDict());key=(idx,tuple(theta[k] for k in work['meta']['keys']))
    if key not in cache:
        f={k:work['arrays'][k][idx] for k in ('x1','x2','x3','w2','w3')}
        gates=instances(work['meta']['templates'],f,theta);qc,positions=sim.compile(gates)
        groups=[i for i,g in enumerate(gates) if g['parameter'] is not None and g['coefficient']!=0]
        cache[key]=(gates,qc,positions,groups)
        while len(cache)>4:cache.popitem(last=False)
    cache.move_to_end(key);gates,qc,positions,groups=cache[key]
    keys=work['meta']['keys'];lookup={k:j for j,k in enumerate(keys)};gradient=np.zeros(len(keys))
    for group in groups[start:stop]:
        g=gates[group];pos=positions[group];original=qc.data[pos];vals=[]
        try:
            for sign in (1,-1):
                op=original.operation.copy();op.params=[g['angle']+sign*np.pi/2]
                qc.data[pos]=original.replace(operation=op);vals.append(sim.evaluate(qc))
        finally:qc.data[pos]=original
        gradient[lookup[g['parameter']]]+=g['coefficient']*.5*np.dot(dz,vals[0]-vals[1])
    return dict(index=idx,start=start,stop=min(stop,len(groups)),gradient=gradient,
        calls=sim.calls-before,seconds=time.perf_counter()-t0,pid=os.getpid(),rss_bytes=psutil.Process().memory_info().rss)


def full_gradient(pool,indices,theta,dz,counts,run=None,context='probe',chunk=24):
    import json
    from pathlib import Path
    jobs=[]
    # Long geometries enter the queue first; reduction keeps submission order.
    for j in sorted(range(len(indices)),key=lambda j:-int(counts[indices[j]])):
        idx=int(indices[j]);n=int(counts[idx])
        for start in range(0,n,chunk):jobs.append((idx,theta,dz[j],start,min(start+chunk,n)))
    t0=time.perf_counter();futs={pool.submit(shift_task,job):i for i,job in enumerate(jobs)};rows=[None]*len(jobs)
    for future in as_completed(futs,timeout=1800):rows[futs[future]]=future.result()
    gradient=np.sum([r['gradient'] for r in rows],axis=0)
    expected=2*sum(int(counts[i]) for i in indices);assert sum(r['calls'] for r in rows)==expected
    if run is not None:
        with (Path(run)/'quantum_tasks.jsonl').open('a') as f:
            f.write(json.dumps(dict(context=context,mode='gate_chunks',wall_seconds=time.perf_counter()-t0,
               chunks=[{k:v for k,v in r.items() if k!='gradient'} for r in rows]))+'\n')
    return gradient,rows


def probe(run,workers_list):
    from pathlib import Path
    run=Path(run);state=pt.load_state(run/'initial.pkl');theta=state['theta'];rows=[];reference=None
    with np.load(run/'dataset.npz') as a:
        counts=60+18*(a['w2']>0).sum(1)+24*(a['w3']>0).sum(1)
    # Eight geometries cover the count distribution; include the dense tail.
    order=np.argsort(counts[:state['plan']['train']],kind='stable');indices=[int(order[int(x)]) for x in np.linspace(0,state['plan']['train']-1,8)]
    for workers in workers_list:
        with pt.pool_for(run,workers) as pool:
            z,_,_=pt.collect(pool,indices,theta,False)
            # Fixed adjoint independent of optimizer, identical in every probe.
            dz=np.full((len(indices),60),1/(60*len(indices)))
            t0=time.perf_counter();gradient,rr=full_gradient(pool,indices,theta,dz,counts,run,f'chunk_probe/{workers}')
            elapsed=time.perf_counter()-t0
        if reference is None:reference=gradient
        np.testing.assert_allclose(reference,gradient,atol=1e-12,rtol=1e-12)
        row=dict(workers=workers,geometries=len(indices),seconds=elapsed,geometries_per_second=len(indices)/elapsed,
             quantum_calls=sum(r['calls'] for r in rr),chunks=len(rr),max_worker_rss=max(r['rss_bytes'] for r in rr),
             mode='gate_chunks',sample_indices=indices,gradient=gradient.tolist())
        rows.append(row);pt.atom_json(run/'performance_probe_chunks.json',rows);print('PERFORMANCE '+str(row),flush=True)
    selected=max(rows,key=lambda r:r['geometries_per_second'])['workers']
    pt.atom_json(run/'selected_workers.json',dict(workers=selected,mode='gate_chunks',identical_gradients_across_workers=True))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--workers',default='1');a=p.parse_args()
    probe(a.run,list(map(int,a.workers.split(','))))
