"""A 3D U-Net that maps a room layout to its airflow, air age and particle field."""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn

from .features import INPUT_CHANNELS, TARGET_CHANNELS


class Block(nn.Module):
    def __init__(self, cin: int, cout: int):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv3d(cin, cout, 3, padding=1),
            nn.GroupNorm(8, cout),
            nn.SiLU(),
            nn.Conv3d(cout, cout, 3, padding=1),
            nn.GroupNorm(8, cout),
            nn.SiLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.body(x)


class RoomNet(nn.Module):
    def __init__(self, width: int = 32, depth: int = 3):
        super().__init__()
        self.depth = depth
        widths = [width * 2**i for i in range(depth + 1)]
        self.down = nn.ModuleList()
        cin = len(INPUT_CHANNELS)
        for w in widths:
            self.down.append(Block(cin, w))
            cin = w
        self.up = nn.ModuleList()
        self.merge = nn.ModuleList()
        for w in reversed(widths[:-1]):
            self.up.append(nn.ConvTranspose3d(cin, w, 2, stride=2))
            self.merge.append(Block(2 * w, w))
            cin = w
        self.head = nn.Conv3d(cin, len(TARGET_CHANNELS), 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shape = x.shape[2:]
        multiple = 2**self.depth
        pad = [(-s) % multiple for s in shape]
        # F.pad takes the last dimension first
        x = F.pad(x, (0, pad[2], 0, pad[1], 0, pad[0]), mode="replicate")
        skips = []
        for i, block in enumerate(self.down):
            x = block(x)
            if i < self.depth:
                skips.append(x)
                x = F.max_pool3d(x, 2)
        for up, merge in zip(self.up, self.merge):
            x = merge(torch.cat([up(x), skips.pop()], dim=1))
        return self.head(x)[:, :, : shape[0], : shape[1], : shape[2]]
