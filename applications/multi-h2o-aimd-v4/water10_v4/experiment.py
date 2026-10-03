"""Bounded loss-driven qubit-ADAPT-inspired trials and honest design fallback.

Classical network uses NumPy analytic backpropagation, with Adam; quantum
derivatives use individually shifted Pauli instances followed by the MLP chain.
"""
from copy import deepcopy
import argparse, csv, json, os, platform, time
from pathlib import Path
import numpy as np
import qiskit, qiskit_aer
from .data import ROOT, load_panel, features, fit_normalizer, encode_features
from .circuit import (seed_templates,complete_templates,active_pool,edit_template,
                      parameter_keys,parameter_key,instances,build_circuit)
from .backend import Backend

def write(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,default=lambda x:x.tolist() if isinstance(x,np.ndarray) else x.item()))

def prepare(out, radii=None):
    panels=json.loads((ROOT/'data_v4/panels.json').read_text())
    train=load_panel(panels['pilot_train_32']); val=load_panel(panels['validation_64'],split='validation')
    norm=fit_normalizer(train)
    cfg=json.loads((ROOT/'configs/data_v4.json').read_text())
    if radii is None: radii=dict(pair_radii=cfg['pair_radii_angstrom'],triple_radii=cfg['triple_radii_angstrom'])
    fs=[]
    for panel in (train,val):
        f=encode_features(features(panel['positions_angstrom'],**radii),norm)
        fs.append([{k:f[k][i] for k in ('x1','x2','x3','w2','w3')} for i in range(len(panel['sample_id']))])
    write(out/'normalizer.json',norm); write(out/'panels.json',panels); write(out/'radii.json',radii)
    return train,val,norm,*fs

def network(seed=916):
    rng=np.random.default_rng(seed)
    p={'W':rng.normal(0,1/np.sqrt(60),(60,16)),'b':np.zeros(16),
       'v':rng.normal(0,.1,16),'c':np.zeros(1)}
    return dict(p=p,m={k:np.zeros_like(v) for k,v in p.items()},v={k:np.zeros_like(v) for k,v in p.items()},step=0)

def predict(net,z):
    p=net['p']; return np.tanh(z@p['W']+p['b'])@p['v']+p['c'][0]

def backward(net,z,y):
    p=net['p']; a=np.tanh(z@p['W']+p['b']); pred=a@p['v']+p['c'][0]
    d=2*(pred-y)/len(y); h=d[:,None]*p['v']*(1-a*a)
    grad=dict(W=z.T@h,b=h.sum(0),v=a.T@d,c=np.array([d.sum()]))
    return float(np.mean((pred-y)**2)),grad,h@p['W'].T

def update(net,grad,lr=.008):
    net['step']+=1; t=net['step']
    for k,g in grad.items():
        net['m'][k]=.9*net['m'][k]+.1*g
        net['v'][k]=.999*net['v'][k]+.001*g*g
        net['p'][k]-=lr*(net['m'][k]/(1-.9**t))/(np.sqrt(net['v'][k]/(1-.999**t))+1e-8)

def metrics(net,z,y,scale):
    pred=predict(net,z); error=pred-y
    return dict(mse=float(np.mean(error**2)),rmse_ev=float(np.sqrt(np.mean(error**2))*scale),
                mae_ev=float(np.mean(abs(error))*scale),r2=float(1-np.sum(error**2)/np.sum((y-y.mean())**2)))

def forward(backend,t,theta,fs,ctx):
    return np.array([backend.evaluate(instances(t,f,theta),f'{ctx}/{i}') for i,f in enumerate(fs)])

def theta_for(t,previous=None):
    previous=previous or {}
    return {k:previous.get(k,.08) for k in parameter_keys(t)}

def checkpoint(path,t,theta,net,norm,**extra):
    write(path,dict(templates=t,theta=theta,network=net,normalizer=norm,
                   gradient_method='parameter_shift',seed=916,rng_state=np.random.default_rng(916).bit_generator.state,
                   quantum_optimizer='SGD lr=0.03; explicit subset',**extra))

def history_row(step,net,zt,zv,yt,yv,scale,phase):
    a=metrics(net,zt,yt,scale); b=metrics(net,zv,yv,scale)
    return dict(step=step,phase=phase,**{'train_'+k:v for k,v in a.items()},**{'validation_'+k:v for k,v in b.items()})

def save_history(out,history):
    write(out/'history.json',history)
    with (out/'history.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(history[0]));writer.writeheader();writer.writerows(history)

def probe(out, kind):
    train,val,norm,ft,fv=prepare(out)
    t=seed_templates() if kind=='seed' else complete_templates(seed_templates())
    theta=theta_for(t); backend=Backend(out/'quantum_ledger.jsonl',call_seconds=60,wall_seconds=240)
    counts=[dict(pairs=int(np.sum(f['w2']>0)),triples=int(np.sum(f['w3']>0))) for f in ft]
    write(out/'resource_plan.json',dict(train_available=3500,validation_available=500,test_sealed=True,
          train_used=32,validation_used=64,counts=counts,templates=t,settings=backend.settings,
          kind=kind,parameter_count=len(theta),versions=versions()))
    g=instances(t,ft[0],theta); start=time.monotonic(); z=backend.evaluate(g,'probe_forward')
    ftime=time.monotonic()-start
    write(out/'forward_probe.json',dict(seconds=ftime,rotation_instances=len(g),
          train_instances=sum(x['stage']=='trainable' for x in g),readout=z))
    key=parameter_keys(t)[0];start=time.monotonic(); j=backend.jacobian(g,[key],'probe_single_shared_parameter')
    gradtime=time.monotonic()-start
    # A central-difference derivative is an independent audit, never training.
    plus=theta.copy();minus=theta.copy();plus[key]+=1e-5;minus[key]-=1e-5
    fd=(backend.evaluate(instances(t,ft[0],plus),'audit_fd_plus')-backend.evaluate(instances(t,ft[0],minus),'audit_fd_minus'))/2e-5
    report=dict(forward_seconds=ftime,shared_parameter_update_seconds=gradtime,
       gradient_max_abs_error=float(np.max(abs(fd-j[:,0]))),calls=backend.calls,
       quantum_parameters=len(theta),train_gate_instances=sum(x['stage']=='trainable' for x in g),
       estimated_all_parameter_shift_seconds=2*sum(x['stage']=='trainable' for x in g)*ftime)
    write(out/'probe.json',report);print(json.dumps(report),flush=True)

def versions():
    return dict(python=platform.python_version(),numpy=np.__version__,qiskit=qiskit.__version__,aer=qiskit_aer.__version__,
                dtype='float64 / complex128',device='CPU',threads=1,mlp='NumPy analytic backpropagation 60-16-1',mlp_parameters=993)

def choose_radii(out):
    panels=json.loads((ROOT/'data_v4/panels.json').read_text()); p=load_panel(panels['pilot_train_32'])
    oxygen=p['positions_angstrom'][:,::3,:]; d=np.linalg.norm(oxygen[:,:,None,:]-oxygen[:,None,:,:],axis=-1)
    values=d[:,np.triu_indices(10,1)[0],np.triu_indices(10,1)[1]].ravel()
    # Quantiles of TRAIN distances only, target sparse but physical near contacts.
    off2=float(np.quantile(values,.18));off3=float(np.quantile(values,.12))
    radii=dict(pair_radii=[off2-.35,off2],triple_radii=[off3-.3,off3])
    f=features(p['positions_angstrom'],**radii)
    write(out/'cutoff_decision.json',dict(source='pilot_train_32 oxygen-pair distances only',
       quantiles={str(q):float(np.quantile(values,q)) for q in [.05,.12,.18,.25,.5,.9]},radii=radii,
       reason='Bound gate-instance shift cost; not a physical accuracy claim',
       active_pairs=np.sum(f['w2']>0,axis=1),active_triples=np.sum(f['w3']>0,axis=1)))
    return radii

def run_search(out):
    radii=choose_radii(out); train,val,norm,ft,fv=prepare(out,radii)
    yt=(train['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev']
    yv=(val['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev']; scale=norm['energy_scale_ev']
    backend=Backend(out/'quantum_ledger.jsonl',max_calls=16000,wall_seconds=2700,call_seconds=60)
    t=seed_templates();theta=theta_for(t);net=network()
    zt=forward(backend,t,theta,ft,'seed_train');zv=forward(backend,t,theta,fv,'seed_validation')
    history=[history_row(0,net,zt,zv,yt,yv,scale,'seed_initial')]
    best_rmse=history[0]['validation_rmse_ev'];best=0
    checkpoint(out/'best_pilot.json',t,theta,net,norm,step=0,rmse_ev=best_rmse)
    # Pilot uses one sample for quantum cost but all 32/64 samples for scores.
    start=time.monotonic();g=instances(t,ft[0],theta);key=parameter_keys(t)[0]
    _,_,dz=backward(net,zt[:1],yt[:1]);jac=backend.jacobian(g,[key],'pilot_shift')
    theta[key]-=.03*float(dz[0]@jac[:,0]);qtime=time.monotonic()-start
    zt=forward(backend,t,theta,ft,'pilot_train');zv=forward(backend,t,theta,fv,'pilot_validation')
    for step in range(1,21):
        _,gr,_=backward(net,zt,yt); update(net,gr)
        row=history_row(step,net,zt,zv,yt,yv,scale,'pilot_mlp_after_one_quantum_update');history.append(row)
        if row['validation_rmse_ev']<best_rmse:
            best_rmse=row['validation_rmse_ev'];best=step
            checkpoint(out/'best_pilot.json',t,theta,net,norm,step=step,rmse_ev=best_rmse)
    save_history(out,history)
    base_net=deepcopy(net);base_theta=theta.copy();base_t=deepcopy(t)
    pool=active_pool();write(out/'active_pool_v1.json',pool)
    policy=dict(rounds=1,candidates=len(pool),steps=3,quantum_batch=[0],mlp_batch='all pilot_train_32',
        scoring='fixed validation_64 normalized MSE',quantum_update='only newly appended shared trainable parameter; existing quantum parameters frozen',
        no_edit_quantum_update='no new parameter; zero structural slot gradient',
        quantum_lr=.03,mlp_lr=.008,tie_tolerance=1e-8,wall_seconds=2700,quantum_call_ceiling=16000,
        batch_order='fixed; no shuffle',seeds=[916],round_start_calls=backend.calls,
        gate_binding='angle = weight * fixed_scale * theta; per-instance shift pi/2 then chain sum')
    write(out/'round_policy.json',policy)
    pilot_ledger=[json.loads(line) for line in (out/'quantum_ledger.jsonl').read_text().splitlines()]
    pilot_forward=float(np.median([r['seconds'] for r in pilot_ledger if not r['shift']]))
    write(out/'pilot_budget_before_search.json',dict(measured_restricted_quantum_update_seconds=qtime,
        median_full_30q_forward_seconds=pilot_forward,train_used=32,validation_used=64,
        candidate_count=16,trial_steps=3,quantum_batch=1,
        estimates_seconds={str(n):{'forward':n*pilot_forward,'all_seed_quantum_parameters':n*60*pilot_forward,
                            'one_shared_parameter':n*20*pilot_forward} for n in (32,250,500,1000,2000,3500)},
        candidate_round_estimate_s=16*(96*4+3*20)*pilot_forward,
        uncertainty='single pilot/seed estimate excludes candidate-dependent entanglement cost; enforced wall/call limits take precedence',
        plan='one round, 16 measured candidates, fixed training32/validation64, then heuristic completion; no data expansion'))
    checkpoint(out/'round_start.json',t,theta,net,norm,policy=policy)
    scores=[];trial_histories={};states={};eligible=[]
    for edit in [None]+pool:
        run_id='no_edit' if edit is None else edit['id']; start=time.monotonic();calls=backend.calls
        ct=deepcopy(base_t) if edit is None else edit_template(base_t,edit)
        th=theta_for(ct,base_theta); nn=deepcopy(base_net)
        newkeys=[k for k in th if k not in base_theta]
        for k in newkeys: th[k]=0.
        zz=forward(backend,ct,th,ft,run_id+'/initial_train');vv=forward(backend,ct,th,fv,run_id+'/initial_val')
        hist=[history_row(0,nn,zz,vv,yt,yv,scale,'trial_initial')]
        directory=out/run_id;directory.mkdir(exist_ok=True)
        checkpoint(directory/'step_0.json',ct,th,nn,norm,step=0,policy=policy)
        eligible.append(dict(run_id=run_id,checkpoint=run_id+'/step_0.json',history=run_id+'/history.json',
                             step=0,rmse_ev=hist[0]['validation_rmse_ev']))
        for step in range(1,policy['steps']+1):
            if newkeys:
                _,_,dz=backward(nn,zz[:1],yt[:1])
                jac=backend.jacobian(instances(ct,ft[0],th),newkeys,run_id+'/parameter_shift')
                for ki,k in enumerate(newkeys):th[k]-=.03*float(dz[0]@jac[:,ki])
                zz=forward(backend,ct,th,ft,run_id+'/updated_train')
                vv=forward(backend,ct,th,fv,run_id+'/updated_val')
            _,gr,_=backward(nn,zz,yt);update(nn,gr)
            hist.append(history_row(step,nn,zz,vv,yt,yv,scale,'candidate_joint' if edit else 'same_budget_control'))
            checkpoint(directory/f'step_{step}.json',ct,th,nn,norm,step=step,policy=policy)
            eligible.append(dict(run_id=run_id,checkpoint=f'{run_id}/step_{step}.json',history=run_id+'/history.json',
                                 step=step,rmse_ev=hist[-1]['validation_rmse_ev']))
        row=dict(id=run_id,before_train_mse=hist[0]['train_mse'],before_validation_mse=hist[0]['validation_mse'],
          after_train_mse=hist[-1]['train_mse'],after_validation_mse=hist[-1]['validation_mse'],
          validation_rmse_ev=hist[-1]['validation_rmse_ev'],seconds=time.monotonic()-start,
          quantum_calls=backend.calls-calls,updated_quantum_parameters=newkeys,
          final_quantum_values={k:th[k] for k in newkeys},actual_steps=policy['steps'])
        scores.append(row);trial_histories[run_id]=hist;states[run_id]=(ct,th,nn)
        save_history(directory,hist)
        checkpoint(directory/'checkpoint.json',ct,th,nn,norm,step=policy['steps'],policy=policy)
        # Preserve every actual checkpoint eligible for the final best-run selection.
        # Candidate checkpoints here are final-step checkpoints; pilot saves its best.
        write(out/'candidate_scores_partial.json',scores);print(json.dumps(row),flush=True)
    control=scores[0]['after_validation_mse']
    for row in scores: row['delta_vs_no_edit']=control-row['after_validation_mse']
    ranked=sorted(scores[1:],key=lambda r:(-r['delta_vs_no_edit'],r['id']))
    for rank,r in enumerate(ranked,1): r['rank']=rank
    chosen=ranked[0]['id'] if ranked[0]['delta_vs_no_edit']>policy['tie_tolerance'] else 'no_edit'
    ct,th,nn=states[chosen]
    checkpoint(out/'adaptive_snapshot.json',ct,th,nn,norm,chosen=chosen)
    write(out/'candidate_scores.json',scores)
    write(out/'selection.json',dict(chosen=chosen,best_candidate=ranked[0],
          reason='max actual loss gain in the explicitly evaluated 16-edit pool' if chosen!='no_edit' else 'no credible positive gain',
          switch_reason='one-round declared budget; required 2B/3B blocks remain incomplete',
          final_design_mode='loss-driven growth + heuristic completion' if chosen!='no_edit' else 'heuristic completion after measured search'))
    # Saved checkpoints only; never associate a curve with a different structure.
    eligible.insert(0,dict(run_id='pilot',checkpoint='best_pilot.json',history='history.json',step=best,rmse_ev=best_rmse))
    winner=min(eligible,key=lambda r:r['rmse_ev'])
    write(out/'eligible_checkpoints.json',eligible)
    write(out/'best_run.json',dict(**winner,
        criterion='lowest validation-64 eV RMSE among saved checkpoints; exact ties earlier run',
        pilot_best_step=best))
    ledger=[json.loads(line) for line in (out/'quantum_ledger.jsonl').read_text().splitlines()]
    fwd=np.median([r['seconds'] for r in ledger if not r['shift']])
    estimates={str(n):dict(one_forward_s=n*fwd,one_all_seed_parameter_update_s=n*60*fwd,
           one_restricted_shared_parameter_update_s=n*20*fwd) for n in (32,250,500,1000,2000,3500)}
    write(out/'pilot_budget.json',dict(actual_train=32,validation=64,train_available=3500,validation_available=500,
          test_labels_accessed=False,measured_pilot_shared_update_seconds=qtime,median_forward_seconds=float(fwd),
          estimates=estimates,estimate_assumptions='serial CPU; 30 seed trainable instances, 10 instances in restricted shared key; actual later structures can be much slower',
          expanded=False,reason='small-panel exploratory search only; dense design costs and generalization evidence do not justify expansion',
          quantum_calls=backend.calls,peak_rss_bytes=max(r['rss_bytes'] for r in ledger),versions=versions(),
          scoring_seconds=sum(r['seconds'] for r in ledger if 'val' in r['context']),
          elapsed_seconds=time.monotonic()-backend.start))

def load_net(data):
    for section in ('p','m','v'):
        data[section]={k:np.array(v) for k,v in data[section].items()}
    return data

def run_design(out, search, bus_only=False):
    snap=json.loads((search/'adaptive_snapshot.json').read_text());norm=snap['normalizer']
    radii=json.loads((search/'radii.json').read_text()); train,val,_,ft,fv=prepare(out,radii)
    t=complete_templates(snap['templates'],bus_only=bus_only);theta=theta_for(t,snap['theta']);net=load_net(snap['network'])
    backend=Backend(out/'quantum_ledger.jsonl',max_calls=3500,wall_seconds=2400,call_seconds=90)
    write(out/'final_templates.json',t)
    # Real training-panel display sample with 3B contacts; no synthetic interactions.
    display=max(range(32),key=lambda i:(min(sum(ft[i]['w3']>0),3),-sum(ft[i]['w2']>0)))
    g=instances(t,ft[display],theta)
    write(out/'display_manifest.json',dict(sample_id=str(train['sample_id'][display]),index=display,split='train',
         templates_version='v2_ten_interacting_wires' if bus_only else 'v1_completion',checkpoint='final_design.json',gates=g,
         active_pairs=np.flatnonzero(ft[display]['w2']>0),active_triples=np.flatnonzero(ft[display]['w3']>0),
         readout='X0..X29 then Z0..Z29; exact ideal expectations; separate bases on hardware'))
    start=time.monotonic(); z=backend.evaluate(g,'final_display_probe');elapsed=time.monotonic()-start
    write(out/'forward_probe.json',dict(seconds=elapsed,rotation_instances=len(g),readout=z))
    yt=(train['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev']
    yv=(val['energy_ev']-norm['energy_mean_ev'])/norm['energy_scale_ev'];scale=norm['energy_scale_ev']
    zt=forward(backend,t,theta,ft,'final_train');zv=forward(backend,t,theta,fv,'final_validation')
    hist=[history_row(0,net,zt,zv,yt,yv,scale,'heuristic_changed_structure')]
    checkpoint(out/'final_design_initial.json',t,theta,net,norm,step=0)
    # One bounded parameter-shift update, then a small classical readout fit.
    key=parameter_keys(t)[0]; _,_,dz=backward(net,zt[:1],yt[:1]); start=time.monotonic()
    jac=backend.jacobian(instances(t,ft[0],theta),[key],'final_parameter_shift')
    theta[key]-=.03*float(dz[0]@jac[:,0]);gradtime=time.monotonic()-start
    zt=forward(backend,t,theta,ft,'final_post_shift_train');zv=forward(backend,t,theta,fv,'final_post_shift_validation')
    hist.append(history_row(1,net,zt,zv,yt,yv,scale,'one_quantum_update'))
    best_rmse=hist[0]['validation_rmse_ev'];best_step=0
    best_state=(deepcopy(net),dict(json.loads((out/'final_design_initial.json').read_text())['theta']))
    if hist[1]['validation_rmse_ev']<best_rmse:
        best_rmse=hist[1]['validation_rmse_ev'];best_step=1;best_state=(deepcopy(net),theta.copy())
    for step in range(2,42):
        _,gr,_=backward(net,zt,yt);update(net,gr,lr=.004)
        row=history_row(step,net,zt,zv,yt,yv,scale,'mlp_refit_quantum_frozen');hist.append(row)
        if row['validation_rmse_ev']<best_rmse:
            best_rmse=row['validation_rmse_ev'];best_step=step;best_state=(deepcopy(net),theta.copy())
    save_history(out,hist);net,theta=best_state
    checkpoint(out/'final_design.json',t,theta,net,norm,step=best_step,rmse_ev=best_rmse)
    # Re-export exactly the delivered checkpoint, not the initial parameter values.
    manifest=json.loads((out/'display_manifest.json').read_text());manifest['gates']=instances(t,ft[display],theta)
    write(out/'display_manifest.json',manifest)
    from qiskit import qpy
    with (out/'final_design.qpy').open('wb') as stream:qpy.dump(build_circuit(manifest['gates'],readout=False),stream)
    np.savez(out/'readouts_last_training_step.npz',train=zt,validation=zv)
    write(out/'summary.json',dict(best_step=best_step,best_validation_rmse_ev=best_rmse,
        first_validation_rmse_ev=hist[0]['validation_rmse_ev'],final_history=hist[-1],
        quantum_parameters=len(theta),mlp_parameters=993,quantum_calls=backend.calls,
        one_shared_parameter_update_seconds=gradtime,display_sample=manifest['sample_id'],
        actual_train_samples=32,validation_samples=64,quantum_joint_updates=1,
        parameter_update_scope=[key],gradient_method='parameter_shift',versions=versions(),
        bus_only=bus_only,design_note='heuristic restriction to ten interacting wires; all 30 qubits remain in the same circuit and readout' if bus_only else 'unrestricted local supports'))
    print(json.dumps(json.loads((out/'summary.json').read_text())),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['probe_seed','probe_full','search','design'])
    p.add_argument('--out',required=True);p.add_argument('--search');p.add_argument('--bus-only',action='store_true');a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    if a.mode.startswith('probe_'):probe(out,a.mode.split('_')[1])
    elif a.mode=='search':run_search(out)
    else:run_design(out,Path(a.search),bus_only=a.bus_only)

if __name__=='__main__':main()
