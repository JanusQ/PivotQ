"""Energy-only is the explicit default; force data must be requested by name."""
from pathlib import Path
import h5py
import numpy as np

def load_dataset(path,split='train',sample_ids=None,include_forces=False):
    with h5py.File(Path(path),'r') as h:
        ids=h['sample_id'].asstr()[:];splits=h['split'].asstr()[:]
        indices=np.where(splits==split)[0]
        if sample_ids is not None:
            lookup={sid:i for i,sid in enumerate(ids)}
            indices=np.array([lookup[sid] for sid in sample_ids],dtype=int)
            if not np.all(splits[indices]==split):raise ValueError('Subset contains another split')
        # HDF5 fancy indexing requires ascending indices; read then preserve requested order.
        result={'positions_angstrom':h['positions_angstrom'][:][indices], 'energy_ev':h['energy_ev'][:][indices],
                'sample_id':ids[indices],'atomic_numbers':h['atomic_numbers'][:],'split':splits[indices]}
        if include_forces:result['forces_ev_per_angstrom']=h['forces_ev_per_angstrom'][:][indices]
    return result

def fit_train_normalizer(training_data):
    if 'split' not in training_data or not np.all(np.asarray(training_data['split'])=='train'):
        raise ValueError('Normalizer must be fitted on a named training subset')
    e=np.asarray(training_data['energy_ev'],dtype=np.float64)
    return {'mean_ev':float(e.mean()),'std_ev':float(e.std())}
