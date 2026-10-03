"""Launch one resumable ten-epoch server run, detached from the SSH session."""
import json,os,subprocess,sys,time
from pathlib import Path
if len(sys.argv) != 2: raise SystemExit('Usage: python '+sys.argv[0]+' <new-run-directory>')
root=Path(__file__).resolve().parents[1];run=root/(sys.argv[1])
run_relative=str(run.relative_to(root));log_relative='reports/'+run.name+'_train.log'
choice=json.loads((run/'selected_workers.json').read_text());assert choice['identical_gradients_across_workers']
assert json.loads((run/'preparation_audit.json').read_text())['passed']
assert json.loads((run/'numerical_preflight.json').read_text())['passed']
if (run/'launch.json').exists():
    prior=json.loads((run/'launch.json').read_text())
    try:os.kill(prior['pid'],0)
    except ProcessLookupError:pass
    else:raise RuntimeError('Existing launched process is still alive; refusing duplicate')
command=['timeout','--signal=TERM','7d',sys.executable,'-B','-u','-m','water10_v4.parallel_training','train',
         '--run',run_relative,'--epochs','10','--workers',str(choice['workers'])]
env=os.environ.copy()
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[key]='1'
(root/'reports').mkdir(exist_ok=True)
with (root/log_relative).open('a') as log:
    proc=subprocess.Popen(command,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
record=dict(pid=proc.pid,start_time=time.time(),command=command,workers=choice['workers'],
            log=log_relative,resume='same train command loads latest.pkl; --epochs is total target, not extra epochs')
(run/'launch.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
