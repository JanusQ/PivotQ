"""Mirror this project with pcie5; copy without deleting target files; verify SHA256 content."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

LOCAL=Path(__file__).resolve().parents[1]
HOST='zhanghao@pcie5-up.rc4ml.org'
REMOTE='/mnt/nfs/home/zhanghao/code/multi-h2o-aimd-v4'
SSH=['ssh','-o','ClearAllForwardings=yes','-o','BatchMode=yes',HOST]
HASH_CODE='''from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);result={}
for p in sorted(root.rglob('*')):
 key=str(p.relative_to(root))
 if p.is_symlink():result[key]={'symlink':str(p.readlink())}
 elif p.is_file():
  h=hashlib.sha256()
  with p.open('rb') as f:
   for block in iter(lambda:f.read(2**20),b''):h.update(block)
  result[key]={'sha256':h.hexdigest(),'size':p.stat().st_size}
print(json.dumps(result,sort_keys=True))
'''

def verify():
    import sys
    local=json.loads(subprocess.check_output([sys.executable,'-c',HASH_CODE,str(LOCAL)],text=True))
    remote=json.loads(subprocess.check_output(SSH+[shlex.join(['python3','-',REMOTE])],input=HASH_CODE,text=True))
    mismatches=[key for key in sorted(set(local)|set(remote)) if local.get(key)!=remote.get(key)]
    report={'matched':not mismatches,'local_files':len(local),'remote_files':len(remote),'mismatches':mismatches}
    print(json.dumps(report,indent=2));return not mismatches

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('direction',choices=['push','pull','verify']);p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    if a.direction=='verify':raise SystemExit(0 if verify() else 1)
    if str(LOCAL)==REMOTE:raise RuntimeError('Run this synchronization helper from the local mirror')
    src,dst=(str(LOCAL)+'/',HOST+':'+REMOTE+'/') if a.direction=='push' else (HOST+':'+REMOTE+'/',str(LOCAL)+'/')
    command=['rsync','-ac','--itemize-changes','-e','ssh -o ClearAllForwardings=yes -o BatchMode=yes']
    if a.dry_run:command+=['--dry-run']
    subprocess.run(command+[src,dst],check=True)

if __name__=='__main__':main()
