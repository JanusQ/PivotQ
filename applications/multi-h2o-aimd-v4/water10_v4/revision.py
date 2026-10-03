"""Revision R1: explicit interaction records, distinct blocks, bounded joint training."""
from copy import deepcopy
from itertools import groupby
from pathlib import Path
import argparse, hashlib, json, time
import numpy as np
from qiskit import QuantumCircuit, qpy
from qiskit.quantum_info import Pauli, Operator
from .data import PAIRS, TRIPLES, features
from .circuit import gate, empty_templates, parameter_keys, instances, append_rotation
from .backend import Backend
from .experiment import (write, prepare, theta_for, network, load_net, forward, backward,
                         update, predict, checkpoint, history_row, save_history, versions)


def revised_templates():
    """Heuristic replacement, never attributed to ADAPT. Ten interacting wires."""
    t=empty_templates()
    one={
      'encoding':[[('Y',0),('X',1)],[('X',1),('Y',2)],[('Y',2),('Z',0)]],
      'trainable':[[('X',0),('Y',2)],[('Y',1),('Z',0)],[('X',2),('Y',1)]]}
    for stage in t:
        for f,specs in enumerate(one[stage]):
            t[stage]['1'][f]=[gate(a,[q],scale=.55 if j==0 else .23) for j,(a,q) in enumerate(specs)]
        for b,n in ((2,10),(3,15)):
            for f in range(n):
                owner=f//5; axis=('YXYXY' if stage=='encoding' else 'XYXYX')[f%5]
                block=[gate(axis,[3*owner+f%3],scale=.55)]
                if f%3==0:
                    block.append(gate('X' if axis=='Y' else 'Y',[3*owner+(f+1)%3],scale=.23))
                if f in ((0,3,6,9) if b==2 else (0,4,8,12)):
                    target=(f//4+(stage=='trainable'))%b
                    sites=[3*target]+[3*k for k in range(b) if k!=target]
                    block.append(gate(('X' if stage=='encoding' else 'Y')+'Z'*(b-1),sites,scale=.28))
                t[stage][str(b)][f]=block
    return t


def block_key(g):
    return (g['stage'],g['body'],tuple(g['molecules']),g['feature'])


def signature(block):
    return tuple((g['axis'],tuple(g['sites'])) for g in block)


def audit_templates(t):
    rows=[]
    for b,n in ((1,3),(2,10),(3,15)):
        for stage in t:
            blocks=t[stage][str(b)];assert len(blocks)==n and all(blocks)
            sigs=[signature(x) for x in blocks];assert len(set(sigs))==n
            for block in blocks:
                for g in block:
                    assert len(g['axis'])==len(g['sites']) and len(set(g['sites']))==len(g['sites'])
                    assert all(0<=q<3*b for q in g['sites']) and g['scale']!=0
                    if len(g['axis'])>1:assert b>1 and all(q%3==0 for q in g['sites'])
                for a,c in zip(block,block[1:]):assert (a['axis'],a['sites'])!=(c['axis'],c['sites'])
            covered={q for block in blocks for g in block for q in g['sites']}
            assert covered==set(range(3*b))
        for f in range(n):
            enc=signature(t['encoding'][str(b)][f]);tr=signature(t['trainable'][str(b)][f])
            assert enc!=tr
            rows.append(dict(body=b,feature=f,encoding=enc,trainable=tr,different=True))
    return dict(passed=True,corresponding_blocks=rows,unique_blocks_per_stage=[3,10,15],
                interaction_note='ten q_(3i) wires entangle; twenty other wires have local rotations and readout')


def primitive_manifest(gates):
    """Exact primitive expansion; cancellation stays within one semantic block."""
    out=[]
    for group,g in enumerate(gates):
        qc=QuantumCircuit(30);append_rotation(qc,g['axis'],g['qubits'],g['angle'])
        for item in qc.data:
            p=dict(name=item.operation.name,qubits=[qc.find_bit(q).index for q in item.qubits],
                   params=[float(x) for x in item.operation.params],group=group,
                   **{k:g[k] for k in ('stage','body','feature','molecules','origin','parameter')})
            if p['name']=='cz' and out and out[-1]['name']=='cz' and block_key(p)==block_key(out[-1]) and set(p['qubits'])==set(out[-1]['qubits']):
                out.pop()
            else:out.append(p)
    return out


def build_block_circuit(gates,shift=None,num_qubits=30,readout=True):
    if shift:
        gates=deepcopy(gates);gates[shift[0]]['angle']+=shift[1]
    qc=QuantumCircuit(num_qubits)
    for p in primitive_manifest(gates):
        getattr(qc,p['name'])(*p['params'],*p['qubits'])
    if readout:
        for axis in ('X','Z'):
            for q in range(num_qubits):qc.save_expectation_value(Pauli(axis),[q],label=f'{axis}{q}')
    return qc


def audit_instances(gates,t):
    keys=[key for key,_ in groupby(gates,key=block_key)]
    assert len(keys)==len(set(keys)), 'noncontiguous / duplicated block'
    for stage in t:
        for b,n in ((1,3),(2,10),(3,15)):
            kk=[k for k in keys if k[:2]==(stage,b)]
            for mols in sorted(set(k[2] for k in kk)):
                assert [k[3] for k in kk if k[2]==mols]==list(range(n))
    enc={(k[1],k[2],k[3]) for k in keys if k[0]=='encoding'}
    tr={(k[1],k[2],k[3]) for k in keys if k[0]=='trainable'}
    assert enc==tr
    for g in gates:
        assert g['qubits']==[g['scope'][q] for q in g['local_qubits']]
        assert (g['parameter'] is None)==(g['stage']=='encoding')
        assert np.isfinite(g['angle'])
    return dict(passed=True,block_instances=len(keys),rotation_instances=len(gates))


def interaction_records(panel,radii):
    raw=features(panel['positions_angstrom'],**radii);result=[]
    for si,sid in enumerate(panel['sample_id']):
        oxy=panel['positions_angstrom'][si,::3];d=np.linalg.norm(oxy[:,None]-oxy[None,:],axis=-1)
        entry=dict(sample_id=str(sid),split=str(panel['split'][si]),molecule_id_base=0,figure_water_id_base=1,
                   radii=radii,monomers=list(range(10)),qubit_map=np.arange(30).reshape(10,3).tolist())
        for b,combos,field in ((2,PAIRS,'pairs'),(3,TRIPLES,'triples')):
            rows=[]
            for ci,mols in enumerate(combos):
                weight=float(raw[f'w{b}'][si,ci]);ds=[float(d[i,j]) for n,i in enumerate(mols) for j in mols[n+1:]]
                rows.append(dict(combination_index=ci,molecule_ids=mols.tolist(),water_ids=(mols+1).tolist(),
                    distances_angstrom=ds,weight=weight,active=weight>0,
                    qubits=[int(3*m+q) for m in mols for q in range(3)],
                    decision='positive smooth weight' if weight>0 else 'zero smooth weight'))
            entry['candidate_'+field]=rows;entry['active_'+field]=[r for r in rows if r['active']]
            entry['candidate_'+field+'_count']=len(rows)
        result.append(entry)
    return result


def run(out,search):
    out.mkdir(parents=True,exist_ok=False)
    radii=json.loads((search/'radii.json').read_text());train,val,norm,ft,fv=prepare(out,radii)
    snap=json.loads((search/'adaptive_snapshot.json').read_text())
    t=revised_templates();write(out/'template_audit.json',audit_templates(t));write(out/'final_templates.json',t)
    # Changing every block is a non-equivalent heuristic replacement. Reinitialize quantum parameters.
    theta=theta_for(t);net=load_net(snap['network'])
    records=interaction_records(train,radii)+interaction_records(val,radii)
    write(out/'interaction_selection.json',records)
    for i,f in enumerate(ft+fv):
        g=instances(t,f,theta);audit_instances(g,t)
        rec=records[i]
        for b,field in ((2,'pairs'),(3,'triples')):
            actual=sorted({tuple(x['molecules']) for x in g if x['stage']=='encoding' and x['body']==b})
            assert actual==[tuple(r['molecule_ids']) for r in rec['active_'+field]]
    yt=(train['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev']
    yv=(val['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev'];scale=norm['energy_scale_ev']
    keys=['b1_f0_g0','b2_f0_g2','b3_f0_g2']
    # Select batch by geometry only, ensuring multi-body keys have active instances.
    qi=sorted(range(32),key=lambda i:(-sum(ft[i]['w3']>0),-sum(ft[i]['w2']>0),i))[:2]
    policy=dict(joint_steps=6,mlp_refit_steps=40,quantum_keys=keys,quantum_batch_indices=qi,
       quantum_batch_ids=[str(train['sample_id'][i]) for i in qi],mlp_batch=32,validation=64,
       quantum_lr=.03,mlp_lr=.004,max_calls=6000,wall_seconds=1800,call_seconds=90,
       no_data_expansion=True,seed=916,gradient_method='individual gate parameter_shift + shared chain sum',
       origin='all final gates heuristic; prior true search archived separately',
       reason='Rebuild distinct contiguous blocks under revised contract; preserve finite ten-wire interacting subsystem')
    write(out/'training_policy.json',policy)
    be=Backend(out/'quantum_ledger.jsonl',max_calls=6000,wall_seconds=1800,call_seconds=90,builder=build_block_circuit)
    write(out/'environment.json',dict(versions=versions(),settings=be.settings,rss_limit=900000000))
    display=max(range(32),key=lambda i:(min(sum(ft[i]['w3']>0),3),-sum(ft[i]['w2']>0)))
    start=time.monotonic();gg=instances(t,ft[qi[0]],theta);be.evaluate(gg,'pilot_forward');ftime=time.monotonic()-start
    start=time.monotonic();jac=be.jacobian(gg,keys,'pilot_three_shared_keys');jtime=time.monotonic()-start
    shift_count=sum(g['parameter'] in keys for g in gg)
    write(out/'pilot_budget.json',dict(forward_seconds=ftime,three_key_shift_seconds=jtime,shift_instances=shift_count,
       rotation_instances=len(gg),active_pairs=len(records[qi[0]]['active_pairs']),active_triples=len(records[qi[0]]['active_triples']),
       train_used=32,validation_used=64,train_available=3500,validation_available=500,
       estimated_six_joint_steps_seconds=6*(96*ftime+2*jtime),
       estimates_seconds={str(n):dict(forward=n*ftime,three_key_update=n*jtime) for n in (32,250,500,1000,2000,3500)},
       estimate_uncertainty='geometry-dependent gate/shift counts; worst-contact pilot, no extrapolated convergence claim',
       expanded=False,reason='Prior poor generalization and new structural validation take priority; fixed bounded pilot'))
    print('PILOT '+(out/'pilot_budget.json').read_text(),flush=True)
    zt=forward(be,t,theta,ft,'initial_train');zv=forward(be,t,theta,fv,'initial_validation')
    hist=[history_row(0,net,zt,zv,yt,yv,scale,'heuristic_initial')]
    (out/'checkpoints').mkdir();best=hist[0]['validation_rmse_ev'];best_step=0
    def save(step):
        checkpoint(out/'checkpoints'/f'step_{step:03d}.json',t,theta,net,norm,step=step,policy=policy)
    save(0);best_state=(deepcopy(net),theta.copy())
    for step in range(1,47):
        if step<=6:
            _,_,dz=backward(net,zt[qi],yt[qi]);grad=np.zeros(len(keys));started=time.monotonic()
            for row,idx in enumerate(qi):
                jj=be.jacobian(instances(t,ft[idx],theta),keys,f'joint_{step}/sample_{idx}')
                grad+=dz[row]@jj
            for key,value in zip(keys,grad):theta[key]-=.03*float(value)
            write(out/f'quantum_update_{step}.json',dict(keys=keys,gradient=grad,theta={k:theta[k] for k in keys},
                   seconds=time.monotonic()-started,batch_ids=policy['quantum_batch_ids']))
            zt=forward(be,t,theta,ft,f'joint_{step}/train');zv=forward(be,t,theta,fv,f'joint_{step}/validation')
        _,gr,_=backward(net,zt,yt);update(net,gr,lr=.004)
        row=history_row(step,net,zt,zv,yt,yv,scale,'joint_parameter_shift' if step<=6 else 'mlp_refit_quantum_frozen')
        hist.append(row);save(step);save_history(out,hist)
        if row['validation_rmse_ev']<best:
            best=row['validation_rmse_ev'];best_step=step;best_state=(deepcopy(net),theta.copy())
        print(json.dumps(row),flush=True)
    net,theta=best_state
    checkpoint(out/'final_design.json',t,theta,net,norm,step=best_step,policy=policy,rmse_ev=best)
    gates=instances(t,ft[display],theta);rec=records[display]
    manifest=dict(sample_id=rec['sample_id'],index=display,split='train',templates_version='revision_r1_distinct_blocks',
      checkpoint='final_design.json',gates=gates,active_pairs=rec['active_pairs'],active_triples=rec['active_triples'],
      readout='X0..X29 then Z0..Z29, ideal expectations, separate hardware bases')
    write(out/'display_manifest.json',manifest)
    qc=build_block_circuit(gates,readout=False)
    with (out/'final_design.qpy').open('wb') as f:qpy.dump(qc,f)
    pm=dict(sample_id=rec['sample_id'],checkpoint='final_design.json',gates=primitive_manifest(gates),
            rotation_groups=len(gates),primitive_gates=len(qc.data),qiskit_depth=qc.depth())
    write(out/'qiskit_primitive_manifest.json',pm)
    ledger=[json.loads(x) for x in (out/'quantum_ledger.jsonl').read_text().splitlines()]
    summary=dict(best_step=best_step,best_validation_rmse_ev=best,best_metrics=hist[best_step],
      initial_metrics=hist[0],last_metrics=hist[-1],quantum_parameters=len(theta),mlp_parameters=993,
      quantum_calls=be.calls,elapsed_seconds=time.monotonic()-be.start,peak_rss_bytes=max(r['rss_bytes'] for r in ledger),
      actual_train_samples=32,validation_samples=64,quantum_joint_updates=6,gradient_method='parameter_shift',
      primitive_gates=len(qc.data),rotation_groups=len(gates),qiskit_depth=qc.depth(),
      origin='heuristic replacement after actual search',test_labels_accessed=False)
    write(out/'summary.json',summary);print('SUMMARY '+json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--search',required=True);a=p.parse_args()
    run(Path(a.out),Path(a.search))
