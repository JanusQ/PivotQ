"""Serial dense Aer statevector with bounded RSS, wall time, calls and an execution ledger."""
import json, os, time, threading
from pathlib import Path
import numpy as np
import psutil
from qiskit_aer import AerSimulator
from .circuit import build_circuit
from .statevector import settings, require_memory, STATEVECTOR_MEMORY_MB

class Backend:
    def __init__(self, path, max_calls=100000, wall_seconds=3600, call_seconds=120, builder=build_circuit):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.calls=0; self.start=time.monotonic(); self.wall_seconds=wall_seconds
        self.max_calls=max_calls; self.call_seconds=call_seconds; self.proc=psutil.Process()
        self.builder=builder
        self.settings=settings()
        self.sim=AerSimulator(**self.settings)
    def evaluate(self,gates,context='forward',shift=None):
        if self.calls>=self.max_calls or time.monotonic()-self.start>self.wall_seconds:
            raise RuntimeError('Declared quantum budget exhausted')
        require_memory()
        start=time.monotonic(); qc=self.builder(gates,shift); build=time.monotonic()-start
        self.calls+=1
        record=dict(call=self.calls,context=context,shift=shift,n_qubits=30,
                    rotation_instances=len(gates),primitive_gates=len(qc.data)-60,
                    build_seconds=build,backend=self.settings,status='pending')
        pending=self.path.with_suffix('.pending.json'); pending.write_text(json.dumps(record))
        stop=threading.Event(); peak=[self.proc.memory_info().rss]
        def watch():
            while not stop.wait(.02):
                peak[0]=max(peak[0],self.proc.memory_info().rss)
                if peak[0]>STATEVECTOR_MEMORY_MB*2**20 or time.monotonic()-start>self.call_seconds:
                    record.update(status='resource_limit',rss_bytes=peak[0],seconds=time.monotonic()-start)
                    pending.write_text(json.dumps(record)); os._exit(86)
        thread=threading.Thread(target=watch,daemon=True); thread.start()
        try:
            result=self.sim.run(qc,shots=1,seed_simulator=916).result()
            if not result.success: raise RuntimeError(str(result.status))
            z=np.array([result.data(0)[f'{axis}{q}'] for axis in ('X','Z') for q in range(30)],float)
            if not np.isfinite(z).all(): raise ValueError('Nonfinite readout')
            record.update(status='completed',metadata=result.results[0].metadata)
            return z
        finally:
            stop.set(); thread.join()
            record.update(seconds=time.monotonic()-start,rss_bytes=max(peak[0],self.proc.memory_info().rss))
            with self.path.open('a') as stream: stream.write(json.dumps(record,default=str)+'\n')
            pending.unlink(missing_ok=True)
    def jacobian(self,gates,keys,context='parameter_shift'):
        jac=np.zeros((60,len(keys))); index={k:i for i,k in enumerate(keys)}
        for i,g in enumerate(gates):
            if g['parameter'] in index and g['coefficient']!=0:
                plus=self.evaluate(gates,context,(i,np.pi/2))
                minus=self.evaluate(gates,context,(i,-np.pi/2))
                jac[:,index[g['parameter']]]+=g['coefficient']*.5*(plus-minus)
        return jac
