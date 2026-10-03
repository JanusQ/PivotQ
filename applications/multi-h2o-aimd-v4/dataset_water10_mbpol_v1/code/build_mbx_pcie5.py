"""Build the preserved MBX archive against the new host's libc; retain original binaries."""
import argparse,hashlib,json,os,platform,shutil,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'vendor/mbx'
WORK=VENDOR/'work_pcie5'
PREFIX=VENDOR/'pcie5'
BUILD_ENV=Path('/mnt/nfs/home/zhanghao/envs/water10-mbx-build')

def main(finish_adapter=False):
    if platform.node()!='pcie5-up.rc4ml.org':raise RuntimeError('Build only on the configured experimental server')
    WORK.mkdir(parents=True,exist_ok=True);PREFIX.mkdir(exist_ok=True)
    env={**os.environ,'PATH':str(BUILD_ENV/'bin')+':'+os.environ['PATH'],'FFTW_HOME':str(BUILD_ENV),
         'CXX':'/usr/bin/g++','CXXFLAGS':'',
         'LDFLAGS':'-Wl,-rpath,'+str(BUILD_ENV/'lib'),'OMP_NUM_THREADS':'1'}
    start=time.monotonic()
    if finish_adapter:
        if not (PREFIX/'lib/libmbx.so').exists() or not (WORK/'src/bblock/system.h').exists():
            raise RuntimeError('Adapter resume requires the completed main library and preserved source tree')
    else:
        with tarfile.open(VENDOR/'mbx_source.tar.gz') as tar:
            tar.extractall(WORK,filter='data')
    commands=[['autoreconf','-fi'],[str(WORK/'configure'),'--prefix='+str(PREFIX),'--enable-shared','--disable-static','--disable-i-pi-plugin'],
              ['make','-C','src','-j4','libmbx.la'],['make','-C','src','install-libLTLIBRARIES'],
              ['/usr/bin/g++','-O2','-fopenmp','-std=c++17','-shared','-fPIC','-I'+str(WORK/'src'),'-I'+str(WORK),'-I'+str(BUILD_ENV/'include'),
               str(VENDOR/'mbx_adapter.cpp'),'-L'+str(PREFIX/'lib'),'-lmbx','-Wl,-rpath,$ORIGIN','-Wl,-rpath,'+str(BUILD_ENV/'lib'),
               '-o',str(PREFIX/'lib/libqaqua_mbx.so')]]
    executed=commands[-1:] if finish_adapter else commands
    for command in executed:
        print(' '.join(command),flush=True)
        subprocess.run(command,cwd=WORK,env=env,check=True)
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    report={'host':platform.node(),'compiler':subprocess.check_output(['/usr/bin/g++','--version'],text=True),
       'archive_sha256':sha(VENDOR/'mbx_source.tar.gz'),'upstream_commit':json.loads((VENDOR/'provenance.json').read_text())['commit'],
       'adapter_sha256':sha(VENDOR/'mbx_adapter.cpp'),'commands':commands,'executed_commands_this_invocation':executed,'fftw_prefix':str(BUILD_ENV),
       'resumed_adapter_only':finish_adapter,'wall_seconds_scope':'this invocation only',
       'earlier_library_build_log':'provenance/mbx_build_library.log' if finish_adapter else None,
       'wall_seconds':time.monotonic()-start,'files':{str(p.relative_to(ROOT)):sha(p) for p in (PREFIX/'lib').iterdir() if p.is_file() and not p.is_symlink()},
       'physical_kernel_changes':False,'old_library_preserved':True}
    (PREFIX/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    # This work directory was created solely by this builder; raw archive and final libraries are preserved.
    shutil.rmtree(WORK)
    print('Build complete:',PREFIX,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--finish-adapter',action='store_true')
    main(parser.parse_args().finish_adapter)
