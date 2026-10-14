"""Loads simulated rooms and serves them as training samples."""

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
# Noise added to the airflow given to the particle network in training, so that it copes
# with the flow network's imperfect airflow when the two are chained.
VELOCITY_NOISE = 0.03


def split_of(case_name: str) -> str:
    """Assign a case to a split from its name, so the split never changes between runs."""
    bucket = int(hashlib.sha256(case_name.encode()).hexdigest(), 16) % 100
    return "test" if bucket < 15 else "validation" if bucket < 25 else "train"


def load_cases(root: Path | list[Path], split: str) -> list[dict]:
    """The finished cases of one split, from one folder or several."""
    roots = [root] if isinstance(root, (str, Path)) else list(root)
    cases = []
    for path in sorted(p for r in roots for p in Path(r).glob(f"*/{RESULT_NAME}")):
        if split_of(path.parent.name) != split:
            continue
        data = np.load(path)
        cases.append({
            "name": path.parent.name,
            "spec": CaseSpec.from_dict(json.loads(str(data["spec"]))),
            "fluid": data["fluid"],
            "velocity": data["velocity"],
            "age": data["age"],
            "particles": data["particles"],
        })
    return cases


class RoomDataset(Dataset):
    """Each item is (inputs, targets, fluid mask).

    For the flow task there is one item per room; for the particle task, one per machine.
    The room is symmetric left to right and front to back, so training samples are randomly
    mirrored, which quadruples the effective amount of data.
    """

    def __init__(self, root: Path | list[Path], split: str, task: str, augment: bool = False):
        self.task = task
        self.augment = augment
        self.cases = load_cases(root, split)
        if task == "flow":
            self.items = [(i, None) for i in range(len(self.cases))]
        else:
            self.items = [(i, m) for i, case in enumerate(self.cases) for m in range(len(case["spec"].machines))]
        names = features.CHANNELS[task]
        self._mirrored = [
            (
                [names["inputs"].index(c) for c in features.MIRRORED[task]["inputs"][axis]],
                [names["targets"].index(c) for c in features.MIRRORED[task]["targets"][axis]],
            )
            for axis in range(2)
        ]

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int):
        case_index, machine = self.items[i]
        case = self.cases[case_index]
        spec = case["spec"]
        if self.task == "flow":
            x = features.flow_inputs(spec)
            y = features.flow_targets(spec, case)
        else:
            velocity = features.scale_velocity(spec, case["velocity"])
            if self.augment:
                velocity = velocity + np.random.normal(0, VELOCITY_NOISE, velocity.shape).astype(np.float32)
            x = features.particle_inputs(spec, machine, velocity * case["fluid"])
            y = features.particle_targets(spec, case, machine)
        mask = case["fluid"].astype(np.float32)[None]
        if self.augment:
            for axis, (in_channels, out_channels) in enumerate(self._mirrored):
                if np.random.rand() < 0.5:
                    x, y, mask = (np.flip(a, axis=axis + 1).copy() for a in (x, y, mask))
                    x[in_channels] *= -1  # coordinates and velocities along the mirrored direction reverse
                    y[out_channels] *= -1
        return tuple(torch.from_numpy(np.ascontiguousarray(a)) for a in (x, y, mask))
