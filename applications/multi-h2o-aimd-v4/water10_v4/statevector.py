"""Dense complex128 simulation: all 2**30 amplitudes, no MPS or qubit pruning."""
import psutil

STATEVECTOR_MEMORY_MB = 32768


def settings(memory_mb=STATEVECTOR_MEMORY_MB):
    if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or memory_mb < STATEVECTOR_MEMORY_MB:
        raise ValueError('Reserve at least 32768 MiB per 30-qubit statevector worker')
    return dict(method='statevector', device='CPU', precision='double',
                max_parallel_threads=1, max_parallel_experiments=1,
                max_parallel_shots=1, max_memory_mb=memory_mb,
                enable_truncation=False)


def require_memory(workers=1, memory_mb=STATEVECTOR_MEMORY_MB):
    settings(memory_mb)
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError('workers must be a positive integer')
    required = workers * memory_mb * 2**20
    available = psutil.virtual_memory().available
    if available < required:
        raise MemoryError(f'Dense statevector needs a {required / 2**30:g} GiB working budget '
                          f'for {workers} worker(s); only {available / 2**30:.1f} GiB available. '
                          'Reduce workers or use a larger host; no MPS fallback.')
