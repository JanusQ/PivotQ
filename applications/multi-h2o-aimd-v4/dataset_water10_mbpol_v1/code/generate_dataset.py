"""Generate the separately authorized MB-pol dataset on pcie5. Never writes DFT labels."""
import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
import csv,fcntl,json,platform,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'inputs'
import argparse
_parser=argparse.ArgumentParser()
_parser.add_argument('--output-dir',type=Path,default=ROOT)
OUT=_parser.parse_args().output_dir.resolve()
sys.path.insert(0,str(ROOT/'code'))
import numpy as np
import h5py,yaml
from ase import Atoms,units
from ase.io import read,write
from ase.calculators.singlepoint import SinglePointCalculator
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from common import read_json,write_json,sha,coordinate_hash,digest,Z,MOLECULE_ID
from mbx_sampler import MBX
from validate_geometry import validate
from descriptors_and_groups import equivalent


def check(ok,message):
    if not ok:raise RuntimeError(message)


def snapshot():
    cfg=yaml.safe_load((SOURCE/'config/pcie5.yaml').read_text())
    calc=MBX(dict(cfg,_root=ROOT))
    provenance=read_json(ROOT/'vendor/mbx/provenance.json')
    check(sha(ROOT/'vendor/mbx/mbx_source.tar.gz')==provenance['files']['mbx_source.tar.gz'],'MBX source archive changed')
    check(sha(ROOT/'vendor/mbx/mbx_adapter.cpp')==provenance['files']['mbx_adapter.cpp'],'MBX adapter source changed')
    check(read_json(SOURCE/'reports/mbx_environment_audit.json')['passed'],'Migrated MBX has not passed its official example')
    paths=[Path(__file__).resolve(),ROOT/'code/common.py',ROOT/'code/mbx_sampler.py',ROOT/'code/validate_geometry.py',
        ROOT/'code/descriptors_and_groups.py',SOURCE/'manifests/selection.json',SOURCE/'manifests/geometry_groups.json',
        SOURCE/'candidates/preselected_unlabeled.h5',SOURCE/'reports/preselection_audit.json',
        ROOT/'vendor/mbx/mbx_adapter.cpp',ROOT/'vendor/mbx/pcie5/lib/libmbx.so',ROOT/'vendor/mbx/pcie5/lib/libqaqua_mbx.so']
    import ase,scipy
    method={'dataset_id':'water10_mbpol_v1','label_source':'MB-pol via MBX System.Energy(true), monomer h2o',
        'mbx_commit':provenance['commit'],'settings':calc.settings,'units':{'positions':'angstrom','energy':'eV','force':'eV/angstrom',
        'kcalmol_to_ev':units.kcal/units.mol,'codata':units.__codata_version__},
        'energy_reference':'Unshifted MBX model energy convention; not absolute electronic energy; no extra monomer subtraction, nuclear repulsion, kinetic energy, D3/D4 or DFT correction.',
        'system':{'water_molecules':10,'atoms':30,'periodic':False,'flexible':True},'forces':'negative full MBX coordinate gradient',
        'default_training_loss':'energy_only','threads':1,'source_files':{str(p.relative_to(ROOT)):sha(p) for p in paths},
        'software':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'ase':ase.__version__,'h5py':h5py.__version__},
        'host':platform.node(),'source_coordinate_plan':SOURCE.name,'DFT_reference':False}
    return cfg,calc,method


def inputs(cfg):
    selection=read_json(SOURCE/'manifests/selection.json');rows=selection['selected'];reserves=selection['reserves']
    check(len(rows)==5000 and len(reserves)==500,'Wrong selected/reserve count')
    check(sha(SOURCE/'candidates/pool.npz')==selection['pool_sha256'],'Source pool changed')
    check(sha(SOURCE/'manifests/candidates.json')==selection['candidate_manifest_sha256'],'Source candidate manifest changed')
    check(sha(SOURCE/'candidates/preselected_unlabeled.h5')==selection['unlabeled_coordinates_sha256'],'Selected coordinates changed')
    check(dict(Counter(r['split'] for r in rows))==cfg['splits'],'Wrong split counts')
    for split,quota in cfg['quotas'].items():check(dict(Counter(r['category'] for r in rows if r['split']==split))==quota,'Category quota mismatch')
    with h5py.File(SOURCE/'candidates/preselected_unlabeled.h5') as h:
        x=h['positions_angstrom'][:]
        check(x.shape==(5000,30,3) and x.dtype==np.float64 and np.isfinite(x).all(),'Invalid coordinates')
        check(np.array_equal(h['atomic_numbers'][:],Z) and not h['pbc'][:].any(),'Atom identity/PBC changed')
        check(list(h['sample_id'].asstr()[:])==[r['sample_id'] for r in rows],'HDF5 IDs reordered')
    check(len(set(r['sample_id'] for r in rows+reserves))==5500,'Duplicate sample ID')
    check(len(set(r['coordinate_sha256'] for r in rows+reserves))==5500,'Exact duplicate coordinate')
    metas=[]
    for r,pos in zip(rows,x):
        check(coordinate_hash(pos)==r['coordinate_sha256'],'Coordinate identity mismatch')
        errors,meta=validate(pos,cfg['geometry'],main=r['split']!='test_ood')
        check(not errors,f"Geometry {r['sample_id']}: {errors}");metas.append(meta)
    for key in ['lineage_root_id','geometry_family_id']:
        groups=defaultdict(set)
        for r in rows+reserves:groups[r[key]].add(r['split'])
        check(all(len(v)==1 for v in groups.values()),key+' leakage')
    cache=read_json(SOURCE/'manifests/geometry_groups.json');check(cache['pool_sha256']==selection['pool_sha256'],'Stale grouping cache')
    selected={r['pool_index']:r for r in rows+reserves}
    for i,j in cache['near_pairs']:
        if i in selected and j in selected:
            check(selected[i]['split']==selected[j]['split']=='test_trajectory','Near duplicate among selected/reserves')
    # Independently repeat near-duplicate checking on the exported 5000 actual geometries.
    near_tests=0;correlated=0
    descriptors=np.array([sorted(m['oo_angstrom']) for m in metas])
    for i,j in cKDTree(descriptors).query_pairs(.03*np.sqrt(45)):
        if rows[i]['split']==rows[j]['split']=='test_trajectory':correlated+=1;continue
        near_tests+=1;check(not equivalent(x[i],x[j]),f'Near duplicate in final coordinates: {i},{j}')
    lookup={r['sample_id']:r for r in rows};nested=selection['nested_train_ids'];full=nested['3500']
    for size in [250,500,1000,2000,3500]:
        ids=nested[str(size)]
        check(len(ids)==size and len(set(ids))==size and ids==full[:size],'Invalid nested training prefix')
        check(all(lookup[s]['split']=='train' for s in ids),'Non-train ID in training subset')
        check(Counter(lookup[s]['category'] for s in ids)=={'thermal':int(size*.7),'distortion':int(size*.2),'boundary':int(size*.1)},'Nested quota mismatch')
    trajectories=defaultdict(list);thermal=defaultdict(list)
    for r in rows:
        if r['split']=='test_trajectory':trajectories[r['trajectory_id']].append(r['time_fs'])
        if r['category']=='thermal':thermal[r['trajectory_id']].append(r['time_fs'])
    check(len(trajectories)==5 and all(len(v)==50 and np.allclose(np.diff(sorted(v)),5) for v in trajectories.values()),'Broken continuous test segments')
    check(all(len(v)<2 or min(np.diff(sorted(v)))>=20-1e-9 for v in thermal.values()),'Thermal selection stride changed')
    ood=[r for r in rows if r['split']=='test_ood'];train_networks={r['network_id'] for r in rows if r['split']=='train'}
    check(Counter(r['ood_subtype'] for r in ood)=={'network':125,'distance':125},'OOD composition changed')
    check(not ({r['network_id'] for r in ood if r['ood_subtype']=='network'}&train_networks),'OOD network leakage')
    check(all(7-1e-8<=r['nearest_cross_oo_angstrom']<=10+1e-8 for r in ood if r['ood_subtype']=='distance'),'OOD range changed')
    report={'passed':True,'samples':5000,'split_counts':cfg['splits'],'coordinate_hashes_verified':5000,'lineage_leakage':0,
        'geometry_family_leakage':0,'exact_duplicates':0,'independent_near_pair_checks':near_tests,'near_duplicate_conflicts':0,
        'correlated_trajectory_pairs_exempted':correlated,'continuous_test_segments':5,'nested_sizes':[250,500,1000,2000,3500],
        'reserves_retained_in_source_only':500,'source_selection_sha256':sha(SOURCE/'manifests/selection.json')}
    write_json(OUT/'reports/input_audit.json',report)
    return rows,x,nested


def numerical_audit(calc,rows,x):
    rng=np.random.default_rng(20260914);groups=defaultdict(list)
    for i,r in enumerate(rows):groups[(r['split'],r['category'],r.get('ood_subtype',''))].append(i)
    chosen=[]
    for key in sorted(groups):chosen.extend(rng.choice(groups[key],size=min(2,len(groups[key])),replace=False).tolist())
    chosen.extend(rng.choice(sorted(set(range(len(x)))-set(chosen)),32-len(chosen),replace=False).tolist())
    records=[];baselines={};start=time.perf_counter()
    for i in chosen:
        pos=x[i];e,f=calc.evaluate(pos);baselines[i]=(e,f.copy());fd=[]
        for component in rng.choice(90,6,replace=False):
            for step in [1e-4,5e-5]:
                xp=pos.copy();xm=pos.copy();xp.flat[component]+=step;xm.flat[component]-=step
                value=-(calc.evaluate(xp)[0]-calc.evaluate(xm)[0])/(2*step)
                fd.append({'component':int(component),'step_angstrom':step,'absolute_error_ev_a':float(abs(value-f.flat[component]))})
        q=Rotation.random(random_state=rng).as_matrix();perm=np.arange(30).reshape(10,3)[rng.permutation(10)].ravel()
        swap=np.arange(30).reshape(10,3);swap[:,[1,2]]=swap[:,[2,1]];swap=swap.ravel()
        sym=[]
        for name,z,expected in [('translation',pos+[11.,-7.,3.],f),('rotation',pos@q,f@q),('water_permutation',pos[perm],f[perm]),('h_exchange',pos[swap],f[swap])]:
            e2,f2=calc.evaluate(z);sym.append({'operation':name,'energy_error_ev':abs(e2-e),'force_error_ev_a':float(abs(f2-expected).max())})
        force=float(np.linalg.norm(f.sum(0)));torque=float(np.linalg.norm(np.cross(pos-pos.mean(0),f).sum(0)))
        passed=max(d['absolute_error_ev_a'] for d in fd)<1e-4 and all(s['energy_error_ev']<1e-8 and s['force_error_ev_a']<1e-6 for s in sym) and force<1e-6 and torque<1e-6
        records.append({'sample_id':rows[i]['sample_id'],'index':i,'finite_differences':fd,'symmetries':sym,'total_force_ev_a':force,'total_torque_ev':torque,'passed':bool(passed)})
    # Record the raw energy convention at an explicitly stated monomer geometry; do not impose a new zero.
    monomer=np.array([[0.,0.,0.],[.9572,0.,0.],[.9572*np.cos(np.deg2rad(104.52)),.9572*np.sin(np.deg2rad(104.52)),0.]])
    monomer_e,_=calc.evaluate(monomer)
    report={'passed':all(r['passed'] for r in records),'samples':len(records),'records':records,'wall_seconds':time.perf_counter()-start,
        'thresholds':{'finite_difference_ev_a':1e-4,'symmetry_energy_ev':1e-8,'symmetry_force_ev_a':1e-6,'total_force_ev_a':1e-6,'total_torque_ev':1e-6},
        'zero_convention_check':{'positions_angstrom':monomer.tolist(),'raw_monomer_energy_ev':monomer_e,'geometry_is_exact_model_minimum':False,'extra_energy_shift_applied':0.},
        'max_fd_error_ev_a':max(v['absolute_error_ev_a'] for r in records for v in r['finite_differences'])}
    write_json(OUT/'reports/numerical_audit.json',report);check(report['passed'],'MB-pol numerical audit failed; see report')
    return baselines


def label(calc,rows,x,identity,baselines):
    checkpoint=OUT/'scratch/labels_checkpoint.npz';e=np.full(len(x),np.nan);f=np.full(x.shape,np.nan)
    if checkpoint.exists():
        with np.load(checkpoint) as h:
            check(str(h['identity'])==identity,'Resume identity changed');e=h['energy_ev'].copy();f=h['forces_ev_per_angstrom'].copy()
    for i,(v,w) in baselines.items():e[i]=v;f[i]=w
    start=time.perf_counter();timings=[]
    for i,pos in enumerate(x):
        if np.isfinite(e[i]) and np.isfinite(f[i]).all():continue
        t=time.perf_counter();e[i],f[i]=calc.evaluate(pos);timings.append(time.perf_counter()-t)
        if (i+1)%250==0 or i+1==len(x):
            tmp=checkpoint.with_suffix('.tmp.npz');np.savez(tmp,identity=identity,energy_ev=e,forces_ev_per_angstrom=f);tmp.replace(checkpoint)
            count=int(np.sum(np.isfinite(e)&np.isfinite(f).all(axis=(1,2))))
            write_json(OUT/'reports/execution_status.json',{'status':'LABELING','completed':count,'target':5000,'dataset_id':'water10_mbpol_v1'})
            print(f'Labels complete: {count}/5000',flush=True)
    check(np.isfinite(e).all() and np.isfinite(f).all(),'Incomplete labels')
    proposal_errors=[abs(e[i]-r['proposal_energy_ev']) for i,r in enumerate(rows) if r.get('proposal_energy_ev') is not None and np.isfinite(r['proposal_energy_ev'])]
    check(not proposal_errors or max(proposal_errors)<1e-8,'Recomputed MB-pol disagrees with preserved trajectory proposals')
    totals=np.linalg.norm(f.sum(axis=1),axis=1);torques=np.linalg.norm(np.cross(x-x.mean(axis=1,keepdims=True),f).sum(axis=1),axis=1)
    check(float(max(totals))<1e-6 and float(max(torques))<1e-6,'Total force/torque failure in full data')
    write_json(OUT/'reports/labeling_metrics.json',{'samples':5000,'new_calls_this_invocation':len(timings),'loop_wall_seconds':time.perf_counter()-start,
        'seconds_per_call_quantiles':np.quantile(timings,[0,.5,.95,1]).tolist() if timings else [],'threads':1,
        'proposal_comparisons':len(proposal_errors),'max_proposal_energy_difference_ev':max(proposal_errors,default=0.),
        'max_total_force_ev_a':float(max(totals)),'max_total_torque_ev':float(max(torques))})
    return e,f


def export(rows,x,e,f,nested,method):
    dest=OUT/'selected';ids=[r['sample_id'] for r in rows];splits=np.array([r['split'] for r in rows]);train=splits=='train'
    shift=float(e[train].mean());std=float(e[train].std());check(std>0,'Degenerate training energies')
    metadata=[]
    for r in rows:
        row=dict(r);row.pop('reference_labeled',None);row.update(dataset_id='water10_mbpol_v1',label_source='MB-pol',energy_labeled=True,forces_labeled=True)
        metadata.append(row)
    locksha=sha(OUT/'config/reference.lock.json')
    tmp=dest/'water10.tmp.h5'
    with h5py.File(tmp,'w') as h:
        for key,data in [('positions_angstrom',x),('energy_ev',e),('forces_ev_per_angstrom',f),('energy_centered_ev',e-shift),('atomic_numbers',Z),('molecule_id',MOLECULE_ID),('pbc',np.array([False]*3))]:
            h.create_dataset(key,data=data,compression='gzip',shuffle=True)
        for key in ['sample_id','split','category','lineage_root_id','geometry_family_id','trajectory_id','scan_id','parent_id','coordinate_sha256']:
            h.create_dataset(key,data=[r.get(key,'') for r in rows],dtype=h5py.string_dtype('utf-8'))
        h.create_dataset('metadata_json',data=[json.dumps(r,ensure_ascii=False) for r in metadata],dtype=h5py.string_dtype('utf-8'))
        h.attrs.update(dataset_id='water10_mbpol_v1',label_source='MB-pol',is_dft=False,default_loss='energy_only',energy_unit='eV',force_unit='eV/angstrom',position_unit='angstrom',
            energy_shift_ev=shift,train_energy_std_ev=std,reference_lock_sha256=locksha,energy_convention=method['energy_reference'])
    tmp.replace(dest/'water10.h5')
    with h5py.File(dest/'water10.h5') as h:
        for key,expected in [('positions_angstrom',x),('energy_ev',e),('forces_ev_per_angstrom',f)]:
            check(h[key].dtype==np.float64 and np.array_equal(h[key][:],expected),'HDF5 round trip mismatch: '+key)
        check(list(h['sample_id'].asstr()[:])==ids,'Export ID order changed')
    for split in sorted(set(splits)):
        indices=np.where(splits==split)[0];atoms=[]
        for i in indices:
            at=Atoms(numbers=Z,positions=x[i],pbc=False);at.info={'sample_id':ids[i],'split':split,'label_source':'MB-pol','dataset_id':'water10_mbpol_v1'}
            at.calc=SinglePointCalculator(at,energy=e[i],forces=f[i]);atoms.append(at)
        path=dest/(split+'.extxyz');write(path,atoms,format='extxyz')
        reread=read(path,index=':');check(len(reread)==len(indices),'Extxyz count mismatch')
        for i,at in zip(indices,reread):
            check(at.info['sample_id']==ids[i] and np.array_equal(at.numbers,Z) and not at.pbc.any(),'Extxyz identity mismatch')
            check(np.max(abs(at.positions-x[i]))<1e-7 and abs(at.get_potential_energy()-e[i])<1e-9 and np.max(abs(at.get_forces()-f[i]))<1e-7,'Extxyz numeric round trip mismatch')
    with (dest/'splits.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['sample_id','split','category','lineage_root_id']);writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
    write_json(dest/'nested_train_ids.json',nested)
    lookup={sid:i for i,sid in enumerate(ids)}
    normalizers={n:{'mean_ev':float(e[[lookup[s] for s in seq]].mean()),'std_ev':float(e[[lookup[s] for s in seq]].std()),'sample_ids_sha256':digest(seq),'count':len(seq)} for n,seq in nested.items()}
    write_json(dest/'normalization.json',{'fit_split':'train','full_train_mean_ev':shift,'full_train_std_ev':std,'subset_normalizers':normalizers,'refit_for_custom_subset':True})
    return shift


def plots(rows,e,f,shift):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data=[]
    for split in sorted(set(r['split'] for r in rows)):
        mask=np.array([r['split']==split for r in rows]);values=e[mask]-shift
        hist,edges=np.histogram(values,bins=40);data.append({'split':split,'energy_centered_ev_histogram':hist.tolist(),'edges_ev':edges.tolist()})
        fig,ax=plt.subplots(figsize=(6,4));ax.hist(values,bins=40);ax.set(title='MB-pol water decamer: '+split,xlabel='Energy minus training mean (eV)',ylabel='Sample count')
        fig.tight_layout();fig.savefig(OUT/'figures'/('energy_'+split+'.png'),dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(6,4));ax.hist(np.linalg.norm(f,axis=2).ravel(),bins=60);ax.set(title='MB-pol water decamer: all atomic forces',xlabel='Force magnitude (eV/angstrom)',ylabel='Atom count')
    fig.tight_layout();fig.savefig(OUT/'figures/force_magnitude.png',dpi=160);plt.close(fig)
    write_json(OUT/'reports/distribution_metrics.json',{'energy_histograms':data,'force_magnitude_quantiles_ev_a':np.quantile(np.linalg.norm(f,axis=2),[0,.5,.95,.99,1]).tolist()})


def main():
    check(platform.node()=='pcie5-up.rc4ml.org','Run experiments only on the designated pcie5 server')
    for d in ['config','selected','reports','figures','scratch','code']:(OUT/d).mkdir(parents=True,exist_ok=True)
    with (OUT/'scratch/generation.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=OUT/'selected/dataset_manifest.json'
        if manifest.exists():
            frozen=read_json(manifest)
            for name,value in frozen['files'].items():check(sha(OUT/name)==value,'Frozen dataset modified: '+name)
            print('Existing frozen MB-pol dataset verified; no overwrite.');return
        start=time.perf_counter();cfg,calc,method=snapshot()
        write_json(OUT/'config/generation.json',{'method':method,'splits':cfg['splits'],'quotas':cfg['quotas'],'numerical_audit_seed':20260914})
        print('Checking 5000 inputs and split isolation...',flush=True);rows,x,nested=inputs(cfg)
        lock=OUT/'config/reference.lock.json'
        if lock.exists():
            previous=read_json(lock)
            check(all(previous.get(k)==v for k,v in method.items()),'Frozen method changed during resume')
            check(previous['numerical_audit_sha256']==sha(OUT/'reports/numerical_audit.json') and previous['input_audit_sha256']==sha(OUT/'reports/input_audit.json'),'Resume audit changed')
            method=previous;baselines={}
        else:
            print('Running 32-geometry MB-pol numerical audit...',flush=True);baselines=numerical_audit(calc,rows,x)
            method['numerical_audit_sha256']=sha(OUT/'reports/numerical_audit.json');method['input_audit_sha256']=sha(OUT/'reports/input_audit.json')
            write_json(lock,method)
        e,f=label(calc,rows,x,digest(method),baselines)
        print('Exporting and reading back HDF5/extxyz...',flush=True);shift=export(rows,x,e,f,nested,method)
        plots(rows,e,f,shift)
        if OUT != ROOT: shutil.copy2(ROOT/'code/dataset_loader.py',OUT/'code/dataset_loader.py')
        from dataset_loader import load_dataset,fit_train_normalizer
        subset=load_dataset(OUT/'selected/water10.h5',sample_ids=nested['250']);check('forces_ev_per_angstrom' not in subset,'Default loader exposes forces')
        check(subset['sample_id'].tolist()==nested['250'],'Subset order changed')
        force_data=load_dataset(OUT/'selected/water10.h5',split='validation',include_forces=True);check(force_data['forces_ev_per_angstrom'].shape==(500,30,3),'Force loader shape')
        n=fit_train_normalizer(subset);expected=read_json(OUT/'selected/normalization.json')['subset_normalizers']['250']
        check(abs(n['mean_ev']-expected['mean_ev'])<1e-12 and abs(n['std_ev']-expected['std_ev'])<1e-12,'Normalizer mismatch')
        try:load_dataset(OUT/'selected/water10.h5',sample_ids=[next(r['sample_id'] for r in rows if r['split']=='test_id')])
        except ValueError:pass
        else:raise RuntimeError('Loader allowed test ID in training')
        quality={'passed':True,'dataset_id':'water10_mbpol_v1','label_source':'MB-pol','samples':5000,'splits':cfg['splits'],'forces_shape':list(f.shape),
            'all_labels_finite':True,'geometry_and_split_audit_passed':True,'numerical_audit_passed':True,'round_trip_passed':True,'loader_checks_passed':True,
            'energy_ev_quantiles':np.quantile(e,[0,.01,.5,.99,1]).tolist(),'wall_seconds':time.perf_counter()-start,'host':platform.node(),
            'DFT_labels':False,'training_performed':False,'source_license':'Original coordinate licensing caveat retained in inputs/reports/public_data_audit.json'}
        write_json(OUT/'reports/final_quality_report.json',quality)
        files={str(p.relative_to(OUT)):sha(p) for folder in ['selected','config','code','figures'] for p in (OUT/folder).rglob('*') if p.is_file()}
        files['reports/final_quality_report.json']=sha(OUT/'reports/final_quality_report.json')
        for name in ['input_audit.json','numerical_audit.json','labeling_metrics.json','distribution_metrics.json']:files['reports/'+name]=sha(OUT/'reports'/name)
        write_json(manifest,{'status':'FROZEN','dataset_id':'water10_mbpol_v1','label_source':'MB-pol','is_dft':False,'samples':5000,'files':files})
        write_json(OUT/'reports/execution_status.json',dict(quality,status='FROZEN'))
        print(json.dumps(quality,indent=2),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if OUT.exists() and not (OUT/'selected/dataset_manifest.json').exists():write_json(OUT/'reports/execution_status.json',{'status':'FAILED_NOT_FROZEN','error':repr(exc)})
        raise
