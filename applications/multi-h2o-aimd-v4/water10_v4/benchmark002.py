"""002 preparation + full-parameter timing only. Performs zero optimizer updates."""
from copy import deepcopy
from pathlib import Path
from itertools import groupby
import argparse,json,time,hashlib
import numpy as np
from qiskit import qpy
from .data import ROOT,load_panel,features,fit_normalizer,encode_features
from .circuit import instances,parameter_keys
from .revision import audit_templates,audit_instances,block_key,signature,build_block_circuit,primitive_manifest
from .backend import Backend
from .experiment import write,versions
from . import mlp_full
from .encoding_angles import ENCODING_MIN_ABS_ANGLE,enforce_encoding_floor

def corrected_templates(old):
    t=deepcopy(old)
    for blocks in t['encoding'].values():
        for block in blocks:
            for g in block:
                g['scale']=1.
                g['encoding_min_abs_angle']=ENCODING_MIN_ABS_ANGLE
    for stage in t:
        for b in ('1','2','3'):
            assert [signature(x) for x in t[stage][b]]==[signature(x) for x in old[stage][b]]
    assert t['trainable']==old['trainable']
    return t

def audit_angles(gates,f):
    audit=[]
    for key,group in groupby(gates,key=block_key):
        group=list(group)
        if key[0]!='encoding':continue
        angles=[g['angle'] for g in group];assert len(set(angles))==1
        first=group[0];expected=first['weight']*float(f[f'x{key[1]}'][first['combination_index'],key[3]])
        minimum=first.get('encoding_min_abs_angle')
        assert all(g.get('encoding_min_abs_angle')==minimum for g in group)
        if minimum is not None:
            assert all(g['encoding_raw_angle']==expected for g in group)
            expected=enforce_encoding_floor(expected,minimum)
            assert abs(angles[0])>=minimum
        assert angles[0]==expected
        assert all(g['coefficient']==g['weight'] for g in group)
        audit.append(dict(body=key[1],molecules=list(key[2]),feature=key[3],angle=angles[0],rotations=len(group),
                          encoding_min_abs_angle=minimum,encoding_angle_clamped=first.get('encoding_angle_clamped',False)))
    return audit

def full_features(panel,radii,norm):
    ff=encode_features(features(panel['positions_angstrom'],**radii),norm)
    return [{k:ff[k][i] for k in ('x1','x2','x3','w2','w3')} for i in range(len(panel['sample_id']))]

def run(out,base):
    out.mkdir(parents=True,exist_ok=False)
    source=json.loads((base/'circuit_seed.json').read_text());radii=json.loads((base/'radii.json').read_text())
    # Read all training/validation data without changing the original split. Test labels remain sealed.
    train=load_panel(split='train');val=load_panel(split='validation');norm=fit_normalizer(train)
    ft=full_features(train,radii,norm);fv=full_features(val,radii,norm)
    t=corrected_templates(source['templates']);theta=source['theta'].copy();keys=parameter_keys(t)
    assert len(keys)==48
    write(out/'template_audit.json',audit_templates(t));write(out/'templates.json',t)
    write(out/'normalizer_train3500.json',norm);write(out/'radii.json',radii)
    write(out/'data_plan.json',dict(train_ids=list(train['sample_id']),validation_ids=list(val['sample_id']),
       train=3500,validation=500,test=1000,test_labels_accessed=False,normalizer='training3500 only',
       preprocessing_formula_retained=True,encoding_min_abs_angle=ENCODING_MIN_ABS_ANGLE,
       angle_policy='encoding_signed_floor_0.1: 1B feature, 2B/3B weighted feature; exact zero maps to +0.1'))
    allcounts=[];gate_counts={b:sum(map(len,t['trainable'][str(b)])) for b in (1,2,3)}
    for split,panel,fs in [('train',train,ft),('validation',val,fv)]:
        for i,f in enumerate(fs):
            pairs=int(sum(f['w2']>0));triples=int(sum(f['w3']>0))
            count=10*gate_counts[1]+pairs*gate_counts[2]+triples*gate_counts[3]
            allcounts.append(dict(split=split,index=i,sample_id=str(panel['sample_id'][i]),category=str(panel['category'][i]),
                       active_pairs=pairs,active_triples=triples,trainable_rotation_instances=count))
    write(out/'population_geometry.json',allcounts)
    # Equal-population strata over actual gradient-instance counts, no energy-based sampling.
    order=sorted(range(3500),key=lambda i:(allcounts[i]['trainable_rotation_instances'],allcounts[i]['sample_id']))
    strata=np.array_split(order,4);reps=[int(x[len(x)//2]) for x in strata]
    extra=[order[int(q*(3499))] for q in np.linspace(0,1,17)]
    probes=list(dict.fromkeys(reps+extra))
    architecture_plan=[dict(widths=list(w),parameters=mlp_full.parameter_count(w)) for w in mlp_full.ARCHITECTURES]
    plan=dict(status='timing_only_pending_user_epoch_count',optimizer_updates=0,batch_size=32,
       quantum_gradient='all 48 shared keys, every trainable gate individually shifted',
       epoch_definition='3500 training samples each once, all quantum/MLP gradients; 500 validation forward only',
       gradient_samples=[allcounts[i] for i in reps],forward_samples=[allcounts[i] for i in probes],
       strata_train_indices=[x.tolist() for x in strata],strata_population=[len(x) for x in strata],
       sample_selection='equal population bins sorted by trainable gate-instance count, median each; no label selection',
       mlp_candidates=architecture_plan,formal_training_epochs=None,plan_b_active=False,
       max_quantum_calls=12000,wall_seconds=2400,per_call_seconds=90,rss_limit_bytes=900000000)
    write(out/'benchmark_plan.json',plan)
    write(out/'corrected_initial.json',dict(templates=t,theta=theta,normalizer=norm,
        source_checkpoint=str(base/'circuit_seed.json'),source_sha256=hashlib.sha256((base/'circuit_seed.json').read_bytes()).hexdigest(),
        status='encoding corrected, not retrained',quantum_parameter_updates=0,mlp_selection='pending formal training',
        gradient_method='parameter_shift'))
    sid=json.loads((base/'display_manifest.json').read_text())['sample_id'];display=list(train['sample_id']).index(sid)
    g=instances(t,ft[display],theta);audit_instances(g,t);aa=audit_angles(g,ft[display])
    write(out/'encoding_angle_audit.json',dict(passed=True,blocks=aa,all_data_scales_one=True,ordered_gate_structure_unchanged=True,
                                              trainable_bindings_unchanged=True))
    qc=build_block_circuit(g,readout=False)
    with (out/'corrected_initial.qpy').open('wb') as stream:qpy.dump(qc,stream)
    write(out/'display_manifest.json',dict(sample_id=sid,split='train',checkpoint='corrected_initial.json',gates=g))
    write(out/'qiskit_primitive_manifest.json',dict(sample_id=sid,checkpoint='corrected_initial.json',gates=primitive_manifest(g),
                    primitive_gates=len(qc.data),qiskit_depth=qc.depth(),rotation_groups=len(g)))
    be=Backend(out/'quantum_ledger.jsonl',max_calls=12000,wall_seconds=2400,call_seconds=90,builder=build_block_circuit)
    write(out/'environment.json',dict(versions=versions(),backend=be.settings,resource_limits=plan))
    print('PREPARED '+json.dumps(dict(train=3500,validation=500,quantum_keys=len(keys),gradient_representatives=plan['gradient_samples'],
                                     mlp_candidates=architecture_plan)),flush=True)
    frows=[];readouts={}
    for idx in probes:
        gates=instances(t,ft[idx],theta);audit_angles(gates,ft[idx]);times=[]
        for repeat in range(2):
            st=time.perf_counter();z=be.evaluate(gates,f'forward_probe/{idx}/{repeat}');times.append(time.perf_counter()-st)
        readouts[idx]=z
        frows.append(dict(**allcounts[idx],seconds=float(np.median(times)),repeats=times,primitive_gates=len(primitive_manifest(gates))))
    write(out/'forward_timings.json',frows)
    nets=[mlp_full.initialize(w) for w in mlp_full.ARCHITECTURES]
    zz=np.array([readouts[i] for i in probes]);yy=(train['energy_ev'][probes]-norm['energy_mean_ev'])/norm['energy_scale_ev']
    repeat=np.arange(32)%len(zz);mlp_times=[]
    for nn in nets:
        mlp_full.backward(nn,zz[repeat],yy[repeat]);started=time.perf_counter()
        for _ in range(100):loss,grad,dz=mlp_full.backward(nn,zz[repeat],yy[repeat])
        elapsed=(time.perf_counter()-started)/100
        mlp_times.append(dict(widths=nn['widths'],parameters=mlp_full.parameter_count(nn['widths']),batch_size=32,
                     forward_backward_seconds=elapsed,initial_loss_not_training=loss,optimizer_updates=nn['step']))
    write(out/'mlp_timings.json',mlp_times)
    measured=[]
    for stratum,idx in enumerate(reps):
        gates=instances(t,ft[idx],theta);n=sum(x['parameter'] is not None for x in gates)
        z=readouts[idx];y=(train['energy_ev'][idx]-norm['energy_mean_ev'])/norm['energy_scale_ev']
        _,_,dz=mlp_full.backward(nets[0],z[None],np.array([y]))
        write(out/'progress.json',dict(status='full_48_key_gradient',stratum=stratum,index=idx,sample_id=str(train['sample_id'][idx]),
                                      expected_shift_calls=2*n,starting_call=be.calls))
        print('GRADIENT_START '+json.dumps(dict(stratum=stratum,sample=allcounts[idx],shift_calls=2*n)),flush=True)
        before=be.calls;st=time.perf_counter();jac=be.jacobian(gates,keys,f'full48_gradient/stratum{stratum}')
        elapsed=time.perf_counter()-st;qgrad=dz[0]@jac
        assert be.calls-before==2*n and np.isfinite(jac).all() and np.isfinite(qgrad).all()
        np.savez(out/f'gradient_stratum_{stratum}.npz',jacobian=jac,loss_gradient=qgrad,keys=np.array(keys))
        row=dict(**allcounts[idx],stratum=stratum,gradient_seconds=elapsed,quantum_keys=len(keys),shift_calls=be.calls-before,
                 gradient_norm=float(np.linalg.norm(qgrad)),max_abs_loss_gradient=float(np.max(abs(qgrad))))
        measured.append(row);write(out/'gradient_timings.json',measured);print('GRADIENT_DONE '+json.dumps(row),flush=True)
    # Independent finite-difference validation of one shared key: never used to update a parameter.
    idx=reps[1];gates=instances(t,ft[idx],theta);key=keys[0]
    jac=np.load(out/'gradient_stratum_1.npz')['jacobian'][:,0]
    plus=theta.copy();minus=theta.copy();plus[key]+=1e-5;minus[key]-=1e-5
    fd=(be.evaluate(instances(t,ft[idx],plus),'FD_audit_only/plus')-be.evaluate(instances(t,ft[idx],minus),'FD_audit_only/minus'))/2e-5
    err=float(np.max(abs(jac-fd)));assert err<1e-6
    # Empirical forward model interpolated across geometry size. Extrapolation uncertainty reported explicitly.
    nc=np.array([r['trainable_rotation_instances'] for r in frows]);tt=np.array([r['seconds'] for r in frows])
    unique=np.unique(nc);med=np.array([np.median(tt[nc==x]) for x in unique])
    predict_forward=lambda n:float(np.interp(n,unique,med))
    estimates=[]
    for b,group in enumerate(strata):
        rep=measured[b];repn=rep['trainable_rotation_instances'];repforward=predict_forward(repn)
        # Scale both the shift count and the cost of each full-circuit evaluation.
        seconds=sum(rep['gradient_seconds']*(allcounts[i]['trainable_rotation_instances']/repn)*
             (predict_forward(allcounts[i]['trainable_rotation_instances'])/repforward) for i in group)
        estimates.append(dict(stratum=b,population=len(group),representative=rep['sample_id'],gradient_seconds=seconds))
    forward_train=sum(predict_forward(r['trainable_rotation_instances']) for r in allcounts[:3500])
    forward_val=sum(predict_forward(r['trainable_rotation_instances']) for r in allcounts[3500:])
    gradient_total=sum(r['gradient_seconds'] for r in estimates);mlp_epoch=max(r['forward_backward_seconds'] for r in mlp_times)*110
    epoch=gradient_total+forward_train+forward_val+mlp_epoch
    ledger=[json.loads(x) for x in (out/'quantum_ledger.jsonl').read_text().splitlines()]
    result=dict(status='awaiting_user_epoch_count',optimizer_updates=0,formal_training_started=False,
      epoch_seconds=epoch,epoch_hours=epoch/3600,planning_range_hours=[epoch*.7/3600,epoch*1.5/3600],
      range_type='engineering allowance, not a statistical confidence interval; state changes and host contention can exceed it',
      training_gradient_seconds=gradient_total,training_forward_seconds=forward_train,validation_forward_seconds=forward_val,
      mlp_forward_backward_seconds_per_epoch_upper=mlp_epoch,
      full_training_shift_calls_per_epoch=2*sum(r['trainable_rotation_instances'] for r in allcounts[:3500]),
      calls_per_epoch=4000+2*sum(r['trainable_rotation_instances'] for r in allcounts[:3500]),
      all_48_keys_full_gradient_samples=measured,stratum_estimates=estimates,
      batch_size=32,quantum_gradient_samples_per_epoch=3500,validation_samples=500,
      fixed_quantum_feature_cache_seconds=forward_train+forward_val,
      plan_b_mlp_only_epoch_seconds=mlp_epoch,plan_b_note='one-time readout caching required after new fixed quantum parameters; no Plan B run yet',
      five_independent_joint_mlp_runs_epoch_hours=5*epoch/3600,
      measured_quantum_calls=be.calls,measured_wall_seconds=time.monotonic()-be.start,
      peak_rss_bytes=max(r['rss_bytes'] for r in ledger),shift_vs_fd_error=err,
      corrected_encoding_structure_unchanged=True,test_labels_accessed=False,
      mlp_candidates=architecture_plan,mlp_comparison_training_done=False,
      caveats=['Four full-gradient geometries, 21 or fewer forward geometries; no full epoch executed.',
               'Same single-thread full30q dense Aer statevector backend; no unmeasured GPU/parallel speedup assumed.',
               'All parameters are eligible; zero geometry-dependent gradients remain mathematically possible.',
               'Quantum SGD/Adam steps and checkpoint I/O are minor unmeasured overhead; training update cost is not omitted from the stated uncertainty.'])
    write(out/'epoch_estimate.json',result);write(out/'progress.json',dict(status='awaiting_user_epoch_count',optimizer_updates=0))
    assert theta==source['theta'] and all(net['step']==0 for net in nets)
    print('EPOCH_ESTIMATE '+json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--base',default='models/initialization');a=p.parse_args()
    run(Path(a.out),Path(a.base))
