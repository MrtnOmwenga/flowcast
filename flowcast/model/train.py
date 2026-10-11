"""Train one model: python -m flowcast.model.train --data data/cases --out data/models/m0 --seed 0

Train several with different seeds to form the ensemble.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .dataset import RoomDataset
from .features import TARGET_CHANNELS
from .network import RoomNet


def masked_error(prediction: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Mean absolute error of each output channel over the cells that contain air."""
    cells = mask.sum(dim=(0, 2, 3, 4)).clamp(min=1)
    return ((prediction - target).abs() * mask).sum(dim=(0, 2, 3, 4)) / cells


def evaluate(model, loader, device) -> torch.Tensor:
    model.eval()
    total = torch.zeros(len(TARGET_CHANNELS))
    count = 0
    with torch.no_grad():
        for x, y, mask in loader:
            x, y, mask = x.to(device), y.to(device), mask.to(device)
            total += masked_error(model(x), y, mask).cpu() * x.shape[0]
            count += x.shape[0]
    return total / max(count, 1)


def baseline_error(train: RoomDataset, held_out: RoomDataset) -> torch.Tensor:
    """Error of always predicting the average training room: the bar a model must beat."""
    mean = torch.stack([train[i][1] for i in range(len(train))]).mean(dim=0)
    errors = [masked_error(mean[None], y[None], mask[None]) for _, y, mask in (held_out[i] for i in range(len(held_out)))]
    return torch.stack(errors).mean(dim=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train one room airflow model.")
    parser.add_argument("--data", type=Path, default=Path("data/cases"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train = RoomDataset(args.data, "train", augment=True)
    validation = RoomDataset(args.data, "validation")
    print(f"device {device}; {len(train.cases)} training rooms ({len(train)} samples), "
          f"{len(validation.cases)} validation rooms ({len(validation)} samples)", flush=True)

    baseline = baseline_error(RoomDataset(args.data, "train"), validation)
    print("baseline  " + "  ".join(f"{n} {v:.4f}" for n, v in zip(TARGET_CHANNELS, baseline)), flush=True)

    loader = DataLoader(train, batch_size=args.batch, shuffle=True, num_workers=args.workers, drop_last=True)
    val_loader = DataLoader(validation, batch_size=args.batch, num_workers=args.workers)
    model = RoomNet(width=args.width).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, max_lr=args.lr, total_steps=args.epochs * len(loader))
    scale = baseline.clamp(min=1e-6).to(device)  # weigh each output by how hard it is

    args.out.mkdir(parents=True, exist_ok=True)
    history = []
    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        started = time.monotonic()
        for x, y, mask in loader:
            x, y, mask = x.to(device), y.to(device), mask.to(device)
            loss = (masked_error(model(x), y, mask) / scale).mean()
            optimiser.zero_grad(set_to_none=True)
            loss.backward()
            optimiser.step()
            schedule.step()
        error = evaluate(model, val_loader, device)
        relative = (error / baseline).mean().item()
        history.append({"epoch": epoch, "validation": error.tolist(), "relative": relative})
        if relative < best:
            best = relative
            torch.save({"model": model.state_dict(), "width": args.width, "epoch": epoch}, args.out / "model.pt")
        print(f"epoch {epoch:3d}  {time.monotonic() - started:5.0f}s  relative to baseline {relative:.3f}  "
              + "  ".join(f"{n} {v:.4f}" for n, v in zip(TARGET_CHANNELS, error)), flush=True)
        (args.out / "history.json").write_text(json.dumps(
            {"baseline": baseline.tolist(), "channels": TARGET_CHANNELS, "epochs": history}, indent=2))


if __name__ == "__main__":
    main()
