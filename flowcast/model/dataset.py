"""Loads simulated rooms and serves them as training samples, one per machine."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from ..sim.export import RESULT_NAME
from ..sim.spec import CaseSpec
from . import features

SPLITS = ("train", "validation", "test")


def split_of(case_name: str) -> str:
    """Assign a case to a split from its name, so the split never changes between runs."""
    bucket = int(hashlib.sha256(case_name.encode()).hexdigest(), 16) % 100
    return "test" if bucket < 15 else "validation" if bucket < 25 else "train"


class RoomDataset(Dataset):
    """Each item is (inputs, targets, fluid mask) for one machine of one simulated room.

    The room is symmetric left to right and front to back, so training samples are
    randomly mirrored, which quadruples the effective amount of data.
    """

    def __init__(self, root: Path, split: str, augment: bool = False):
        self.augment = augment
        self.cases = []
        self.items: list[tuple[int, int | None]] = []
        for path in sorted(Path(root).glob(f"*/{RESULT_NAME}")):
            if split_of(path.parent.name) != split:
                continue
            data = np.load(path)
            spec = CaseSpec.from_dict(json.loads(str(data["spec"])))
            case = {
                "name": path.parent.name,
                "spec": spec,
                "fluid": data["fluid"],
                "velocity": data["velocity"],
                "age": data["age"],
                "particles": data["particles"],
            }
            index = len(self.cases)
            self.cases.append(case)
            machines = range(len(spec.machines)) if spec.machines else [None]
            self.items.extend((index, machine) for machine in machines)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int):
        case_index, machine = self.items[i]
        case = self.cases[case_index]
        x = features.inputs(case["spec"], machine)
        y = features.targets(case["spec"], case, machine)
        mask = case["fluid"].astype(np.float32)[None]
        if self.augment:
            for axis, component in ((1, 0), (2, 1)):  # array axis, velocity component
                if np.random.rand() < 0.5:
                    x, y, mask = (np.flip(a, axis=axis) for a in (x, y, mask))
                    x, y = x.copy(), y.copy()
                    y[component] *= -1  # velocity along the mirrored direction reverses
                    x[3 + component] *= -1  # and so does that coordinate channel
        return tuple(torch.from_numpy(np.ascontiguousarray(a)) for a in (x, y, mask))
