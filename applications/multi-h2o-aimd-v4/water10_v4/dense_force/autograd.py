"""PyTorch bridge with analytic second derivatives for energy-derived forces."""
import torch
from .adjoint import DenseAdjoint


def array(tensor):return tensor.detach().cpu().numpy()
def tensor(value,like):return torch.as_tensor(value,dtype=like.dtype,device=like.device)


class _VJP(torch.autograd.Function):
    @staticmethod
    def forward(ctx,angles,weights,engine):
        ctx.save_for_backward(angles,weights);ctx.engine=engine
        return tensor(engine.vjp(array(angles),array(weights)),angles)

    @staticmethod
    def backward(ctx,direction):
        angles,weights=ctx.saved_tensors
        h,z_dot=ctx.engine.hvp(array(angles),array(weights),array(direction))
        return tensor(h,angles),tensor(z_dot,weights),None


class _Readouts(torch.autograd.Function):
    @staticmethod
    def forward(ctx,angles,engine):
        if angles.dtype!=torch.float64 or angles.device.type!='cpu':
            raise ValueError('Dense force engine requires CPU float64 angles')
        ctx.save_for_backward(angles);ctx.engine=engine
        return tensor(engine.forward(array(angles)),angles)

    @staticmethod
    def backward(ctx,weights):
        (angles,)=ctx.saved_tensors
        return _VJP.apply(angles,weights,ctx.engine),None


def readouts(angles,engine):return _Readouts.apply(angles,engine)
