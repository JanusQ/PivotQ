"""Bounded dense tanh MLP candidates with analytic reverse-mode gradients."""
import numpy as np

ARCHITECTURES=[(60,16,1),(60,32,16,1),(60,64,32,1),(60,64,64,32,1),(60,96,64,32,1)]

def parameter_count(widths):
    return sum((a+1)*b for a,b in zip(widths,widths[1:]))

def initialize(widths,seed=916):
    if parameter_count(widths)>15000:raise ValueError('MLP parameter budget exceeded')
    rng=np.random.default_rng(seed)
    p={}
    for i,(a,b) in enumerate(zip(widths,widths[1:])):
        p[f'W{i}']=rng.normal(0,np.sqrt(2/(a+b)),(a,b))
        p[f'b{i}']=np.zeros(b)
    return dict(widths=list(widths),p=p,m={k:np.zeros_like(v) for k,v in p.items()},
                v={k:np.zeros_like(v) for k,v in p.items()},step=0,seed=seed)

def predict(net,z):
    a=np.asarray(z);n=len(net['widths'])-1
    for i in range(n):
        a=a@net['p'][f'W{i}']+net['p'][f'b{i}']
        if i<n-1:a=np.tanh(a)
    return a[:,0]

def backward(net,z,y):
    n=len(net['widths'])-1;acts=[np.asarray(z)]
    for i in range(n):
        h=acts[-1]@net['p'][f'W{i}']+net['p'][f'b{i}']
        acts.append(np.tanh(h) if i<n-1 else h)
    error=acts[-1][:,0]-y;delta=(2/len(y))*error[:,None];grad={}
    for i in reversed(range(n)):
        grad[f'W{i}']=acts[i].T@delta;grad[f'b{i}']=delta.sum(0)
        delta=delta@net['p'][f'W{i}'].T
        if i>0:delta*=1-acts[i]**2
    return float(np.mean(error**2)),grad,delta

def adam_step(net,grad,lr=.001):
    """Only call after formal training epoch budget has been approved."""
    net['step']+=1;t=net['step']
    for k,g in grad.items():
        net['m'][k]=.9*net['m'][k]+.1*g
        net['v'][k]=.999*net['v'][k]+.001*g*g
        net['p'][k]-=lr*(net['m'][k]/(1-.9**t))/(np.sqrt(net['v'][k]/(1-.999**t))+1e-8)
