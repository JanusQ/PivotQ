"""Full molecular permutations + exhaustive H exchanges + proper Kabsch rotation.
Sorted O-O distances are only a necessary prefilter; never a duplicate verdict.
"""
import itertools
import networkx as nx
import numpy as np
from scipy.spatial.distance import pdist, squareform

SWAPS = np.array(list(itertools.product([False,True],repeat=10)))

def equivalent(a,b,rmsd_tol=.03,oo_tol=.03):
    a=np.asarray(a).reshape(30,3); b=np.asarray(b).reshape(30,3)
    from validate_geometry import descriptor
    if np.sum((descriptor(a)[:435]-descriptor(b)[:435])**2) >= 30**2*rmsd_tol**2: return False
    oa=pdist(a[::3]); ob=pdist(b[::3])
    if np.sqrt(np.mean((np.sort(oa)-np.sort(ob))**2)) >= oo_tol:
        return False
    da=squareform(oa); db=squareform(ob)
    ga=nx.from_numpy_array(da); gb=nx.from_numpy_array(db)
    # Any individual pair difference cannot exceed the RMS times sqrt(45).
    gm=nx.algorithms.isomorphism.GraphMatcher(ga,gb,edge_match=lambda x,y: abs(x['weight']-y['weight']) < oo_tol*np.sqrt(45))
    ac=a-a.mean(0)
    for mapping in gm.isomorphisms_iter():
        ids=[mapping[i] for i in range(10)]
        if np.sqrt(np.mean((da-db[np.ix_(ids,ids)])[np.triu_indices(10,1)]**2)) >= oo_tol: continue
        base=b.reshape(10,3,3)[ids]
        batch=np.broadcast_to(base,(1024,10,3,3)).copy()
        i,j=np.where(SWAPS)
        batch[i,j,1]=base[j,2]; batch[i,j,2]=base[j,1]
        batch=batch.reshape(1024,30,3)
        batch-=batch.mean(axis=1,keepdims=True)
        u,s,vh=np.linalg.svd(np.einsum('nai,aj->nij',batch,ac))
        correction=np.ones((1024,3)); correction[:,-1]=np.linalg.det(u@vh)
        rot=(u*correction[:,None,:])@vh
        rms=np.sqrt(np.mean(np.sum((batch@rot-ac)**2,axis=2),axis=1))
        if rms.min() < rmsd_tol: return True
    return False

def fps(values,n,initial=0):
    values=np.asarray(values); n=min(n,len(values))
    selected=[]; mind=np.full(len(values),np.inf); k=initial
    for _ in range(n):
        selected.append(k)
        mind=np.minimum(mind,np.mean((values-values[k])**2,axis=1))
        mind[selected]=-np.inf
        k=int(np.argmax(mind))
    return selected
