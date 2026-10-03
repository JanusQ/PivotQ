"""Energy inference with the same block-preserving compiler used in revision R1."""
from .model import Water10V4
from .backend import Backend
from .revision import build_block_circuit

class Water10Revision(Water10V4):
    def __init__(self,checkpoint,ledger_path):
        super().__init__(checkpoint,ledger_path,backend=Backend(ledger_path,builder=build_block_circuit))
