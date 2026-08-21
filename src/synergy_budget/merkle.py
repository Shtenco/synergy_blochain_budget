from __future__ import annotations
import hashlib
from collections.abc import Iterable, Sequence
ZERO_ROOT = "0"*64

def _h(data: bytes)->bytes: return hashlib.sha256(data).digest()
def leaf_hash(payload: bytes)->bytes: return _h(b"\x00"+payload)
def branch_hash(left: bytes,right: bytes)->bytes: return _h(b"\x01"+left+right)

def merkle_root(payloads: Iterable[bytes])->str:
    level=[leaf_hash(p) for p in payloads]
    if not level: return ZERO_ROOT
    while len(level)>1:
        if len(level)%2: level.append(level[-1])
        level=[branch_hash(level[i],level[i+1]) for i in range(0,len(level),2)]
    return level[0].hex()

def merkle_proof(payloads: Sequence[bytes], index: int) -> list[dict[str,str]]:
    if not payloads: raise ValueError("cannot prove an empty tree")
    if index < 0 or index >= len(payloads): raise IndexError(index)
    level=[leaf_hash(p) for p in payloads]
    idx=index; proof=[]
    while len(level)>1:
        if len(level)%2: level.append(level[-1])
        sibling=idx-1 if idx%2 else idx+1
        proof.append({"position":"left" if sibling < idx else "right","hash":level[sibling].hex()})
        idx//=2
        level=[branch_hash(level[i],level[i+1]) for i in range(0,len(level),2)]
    return proof

def verify_merkle_proof(payload: bytes, proof: Sequence[dict[str,str]], root: str) -> bool:
    current=leaf_hash(payload)
    try:
        for step in proof:
            sibling=bytes.fromhex(step["hash"])
            if step["position"]=="left": current=branch_hash(sibling,current)
            elif step["position"]=="right": current=branch_hash(current,sibling)
            else: return False
    except (KeyError,ValueError): return False
    return current.hex()==root
