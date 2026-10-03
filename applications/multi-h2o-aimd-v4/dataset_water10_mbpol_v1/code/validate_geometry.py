"""Fixed molecular identity, geometry domain and deterministic derived metadata."""
import itertools
import numpy as np
import networkx as nx
from scipy.spatial.distance import pdist, squareform

def metadata(x, cfg):
    x = np.asarray(x, dtype=np.float64).reshape(10, 3, 3)
    v = x[:, 1:] - x[:, :1]
    r = np.linalg.norm(v, axis=-1)
    angles = np.degrees(np.arccos(np.clip(np.sum(v[:,0]*v[:,1],axis=1)/(r[:,0]*r[:,1]), -1, 1)))
    oo = squareform(pdist(x[:,0]))
    graph = nx.DiGraph()
    graph.add_nodes_from(range(10))
    for i,j in itertools.permutations(range(10), 2):
        cos = v[i] @ (x[j,0]-x[i,0]) / (r[i]*oo[i,j])
        if oo[i,j] < cfg['hbond_oo'] and np.any(cos > np.cos(np.radians(cfg['hbond_angle_deg']))):
            graph.add_edge(i,j)
    tri = [(i,j,k) for i,j,k in itertools.combinations(range(10),3) if max(oo[i,j],oo[i,k],oo[j,k]) < 4.5]
    return dict(oh_angstrom=r.tolist(), hoh_degrees=angles.tolist(), oo_angstrom=oo[np.triu_indices(10,1)].tolist(),
                radius_gyration_angstrom=float(np.sqrt(np.mean(np.sum((x[:,0]-x[:,0].mean(0))**2,axis=1)))),
                pair_edges=int(np.sum(np.triu(oo < 6.5,1))), triple_relations=len(tri),
                hbond_edges=list(graph.edges()), network_id=nx.weisfeiler_lehman_graph_hash(graph, iterations=5),
                main_distance_bin='separated' if np.max(np.min(oo+np.eye(10)*1e6,axis=1)) >= 7 else 'cluster')

def validate(x, cfg, main=False):
    x = np.asarray(x, dtype=np.float64)
    if x.shape != (30,3) or not np.isfinite(x).all():
        return ['shape_or_nonfinite'], None
    m = metadata(x, cfg)
    r, angles, oo = np.array(m['oh_angstrom']), np.array(m['hoh_degrees']), np.array(m['oo_angstrom'])
    errors = []
    for name,values,limits in [('oh',r,cfg['main_oh'] if main else cfg['hard_oh']), ('angle',angles,cfg['main_angle'] if main else cfg['hard_angle'])]:
        if values.min()<limits[0] or values.max()>limits[1]: errors.append(name+'_outside_domain')
    if oo.min() < cfg['min_oo']: errors.append('oo_collision')
    dist = squareform(pdist(x))
    mids = np.repeat(np.arange(10),3)
    if dist[mids[:,None]!=mids[None,:]].min() < cfg['min_nonbonded']: errors.append('nonbonded_collision')
    h = np.where(np.tile([False, True, True],10))[0]
    if np.any(np.argmin(dist[h][:,::3],axis=1)!=mids[h]): errors.append('hydrogen_identity_or_transfer')
    return errors, m

def descriptor(x):
    """Invariant prefilter / diversity descriptor, NEVER the final equivalence test."""
    x=np.asarray(x).reshape(10,3,3)
    oh=np.linalg.norm(x[:,1:]-x[:,:1],axis=2)
    v=x[:,1:]-x[:,:1]
    cos=np.sum(v[:,0]*v[:,1],axis=1)/(oh[:,0]*oh[:,1])
    oxy=x[:,0]; hyd=x[:,1:].reshape(20,3)
    return np.r_[np.sort(pdist(oxy)),np.sort(np.linalg.norm(oxy[:,None]-hyd[None,:],axis=2).ravel()),
                 np.sort(pdist(hyd)),np.sort(oh.ravel()),np.sort(cos)]
