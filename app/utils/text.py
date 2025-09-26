from __future__ import annotations
import random
from typing import Sequence

def pick(seq: Sequence[str]) -> str:
    return random.choice(seq) if seq else ""
