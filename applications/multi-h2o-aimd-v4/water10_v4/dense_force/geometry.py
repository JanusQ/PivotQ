"""Versioned smooth encoding; original frozen-model encoding remains untouched.

O coordinates are mass-centered. Each water supplies Oxyz and bisector xyz.
The former azimuth slot encodes bisector x/y with two noncommuting rotations;
the former polar slot encodes bisector z. Trainable templates retain 48 keys.
"""
from itertools import combinations
import torch

ENCODING_VERSION='centered_bisector_xyz_no_floor_v1'


def switch(d,radii):
    on,off=radii
    if not 0<on<off:raise ValueError('Invalid radii')
    t=torch.clamp((d-on)/(off-on),0.,1.)
    return torch.clamp(1-10*t**3+15*t**4-6*t**5,0.,1.)


def geometry(positions,normalizer,radii):
    if positions.shape!=(30,3) or positions.dtype!=torch.float64:raise ValueError('Expected float64 (30,3) coordinates')
    masses=positions.new_tensor([15.999,1.008,1.008]*10)
    centered=positions-(positions*masses[:,None]).sum(0)/masses.sum()
    xyz=centered.reshape(10,3,3);oxygen=xyz[:,0]
    bonds=xyz[:,1:]-oxygen[:,None]
    lengths=torch.linalg.vector_norm(bonds,dim=-1)
    if bool((lengths.detach()<1e-8).any()):raise ValueError('Degenerate OH bond')
    unit=bonds/lengths[...,None];bisector=unit.sum(1)
    norm=torch.linalg.vector_norm(bisector,dim=-1)
    if bool((norm.detach()<1e-8).any()):raise ValueError('Undefined bisector')
    bisector=bisector/norm[:,None]
    cross=torch.linalg.vector_norm(torch.linalg.cross(unit[:,0],unit[:,1]),dim=-1)
    if bool((cross.detach()<1e-8).any()):raise ValueError('Collinear HOH is outside supported geometry domain')
    angle=torch.atan2(cross,(unit[:,0]*unit[:,1]).sum(-1))
    oh=torch.pi/2*torch.tanh((lengths-normalizer['oh_mean'])/normalizer['oh_scale'])
    x1=torch.cat((oh,angle[:,None]),-1)
    mean=positions.new_tensor(normalizer['oxygen_mean']);scale=positions.new_tensor(normalizer['oxygen_scale'])
    o=torch.pi/2*torch.tanh((oxygen-mean)/scale)
    return x1,o,bisector,oxygen


def build_angles(positions,theta,templates,normalizer,radii):
    x1,oxygen_features,bisector,oxygen=geometry(positions,normalizer,radii)
    groups={1:[(i,) for i in range(10)],2:list(combinations(range(10),2)),3:list(combinations(range(10),3))}
    weights={}
    for body in (2,3):
        for mols in groups[body]:
            ds=[torch.linalg.vector_norm(oxygen[i]-oxygen[j]) for i,j in combinations(mols,2)]
            if any(float(d.detach())<1e-8 for d in ds):raise ValueError('Coincident oxygen atoms')
            if body==2:w=switch(ds[0],radii['pair_radii'])
            else:
                a,b,c=[switch(d,radii['triple_radii']) for d in ds]
                w=torch.clamp(a*b+a*c+b*c-2*a*b*c,0.,1.)
            weights[mols]=w
    gates=[];angles=[]
    for stage in ('encoding','trainable'):
        for body in (1,2,3):
            for mols in groups[body]:
                weight=positions.new_tensor(1.) if body==1 else weights[mols]
                # Quintic switch has zero first/second derivatives at support edge.
                if float(weight.detach())<=0:continue
                wires=[3*m+q for m in mols for q in range(3)]
                for f,block in enumerate(templates[stage][str(body)]):
                    for j,g in enumerate(block):
                        base=dict(axis=g['axis'],qubits=[wires[q] for q in g['sites']],stage=stage,body=body,molecules=list(mols),feature=f,
                                  origin='smooth_encoding_v1' if stage=='encoding' else g['origin'],scope=wires,local_qubits=g['sites'],
                                  weight=float(weight.detach()),coefficient=float(weight.detach())*g['scale'])
                        if stage=='trainable':
                            key=f'b{body}_f{f}_g{j}'
                            gates.append(dict(base,parameter=key));angles.append(weight*g['scale']*theta[key])
                        elif body==1:
                            gates.append(dict(base,parameter=None));angles.append(x1[mols[0],f]*g['scale'])
                        else:
                            owner=mols[f//5];channel=f%5
                            if channel<3:values=[(base['axis'],oxygen_features[owner,channel])]
                            elif channel==3:
                                axis=base['axis'];alt=('Y' if axis[0]=='X' else 'X')+axis[1:]
                                values=[(axis,bisector[owner,0]),(alt,bisector[owner,1])]
                            else:values=[(base['axis'],bisector[owner,2])]
                            for axis,value in values:
                                gates.append(dict(base,axis=axis,parameter=None));angles.append(weight*g['scale']*value)
    return gates,torch.stack(angles)
