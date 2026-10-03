"""Run training only after full-state acceptance, then 50 fs MD; never draw fake data."""
import argparse,json,os,shutil,subprocess,sys,time,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from water10_v4.dense_force.training import json_save


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--acceptance',type=Path,required=True);p.add_argument('--preflight-pid',type=int,required=True);a=p.parse_args()
    run=a.run
    with (run/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if json.loads((run/'software_acceptance.json').read_text()).get('passed') is not True:
            raise RuntimeError('Software acceptance must pass before launch')
        json_save(run/'supervisor.json',dict(stage='waiting_full_state_acceptance',pid=os.getpid(),time=time.time()))
        while True:
            if (run/'STOP').exists():return
            try:report=json.loads(a.acceptance.read_text())
            except (OSError,json.JSONDecodeError):report={}
            if report.get('status')=='passed':break
            try:os.kill(a.preflight_pid,0)
            except ProcessLookupError:raise RuntimeError('Preflight ended without passing; training not started')
            time.sleep(15)
        shutil.copy2(a.acceptance,run/'acceptance.json')
        environment=os.environ.copy();environment['PYTHONDONTWRITEBYTECODE']='1'
        for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:environment[name]='1'
        for stage,module in [('training','water10_v4.dense_force.training'),('aimd','water10_v4.dense_force.aimd')]:
            if (run/'STOP').exists():return
            command=[sys.executable,'-B','-u','-m',module]+(['train'] if stage=='training' else [])+['--run',str(run),'--threads','8']
            with (run/f'{stage}.log').open('a') as log:
                process=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT)
                json_save(run/'supervisor.json',dict(stage=stage,pid=os.getpid(),child_pid=process.pid,time=time.time()))
                rc=process.wait()
            if (run/'STOP').exists():return
            if rc:raise RuntimeError(f'{stage} failed with status {rc}; inspect log and checkpoints')
        json_save(run/'supervisor.json',dict(stage='trajectory_complete_plot_pending',pid=os.getpid(),time=time.time()))

if __name__=='__main__':main()
