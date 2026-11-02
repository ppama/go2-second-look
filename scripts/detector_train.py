#!/usr/bin/env python
"""Train a Siamese change detector on simulated pairs. A shared ResNet18 encodes both views."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

from scout.detector import ChangeNet, MEAN, STD

DATA = ROOT / "output" / "detector" / "data"
OUT = ROOT / "output" / "detector"
EPOCHS, BATCH, LR = 6, 48, 2e-4


class Pairs(Dataset):
    def __init__(self, split, augment):
        self.dir, self.augment = DATA / split, augment
        self.rows = json.loads((self.dir / "labels.json").read_text())
        self.norm = transforms.Normalize(MEAN, STD)
        self.jitter = transforms.ColorJitter(0.3, 0.3, 0.3, 0.05)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        row = self.rows[i]
        a = Image.open(self.dir / f"{row['id']:05d}_a.jpg").convert("RGB")
        b = Image.open(self.dir / f"{row['id']:05d}_b.jpg").convert("RGB")
        ta, tb = transforms.functional.to_tensor(a), transforms.functional.to_tensor(b)
        if self.augment:
            if random.random() < 0.5:
                ta, tb = ta.flip(2), tb.flip(2)
            ta, tb = self.jitter(ta), self.jitter(tb)
        return self.norm(ta), self.norm(tb), float(row["changed"]), row["kind"]


def evaluate(net, loader, device):
    net.eval()
    probs, labels, kinds = [], [], []
    with torch.no_grad():
        for a, b, y, kind in loader:
            with torch.autocast("cuda"):
                probs.append(torch.sigmoid(net(a.to(device), b.to(device))).float().cpu())
            labels.append(y)
            kinds += list(kind)
    probs, labels = torch.cat(probs).numpy(), torch.cat(labels).numpy()
    pred = probs > 0.5
    result = {"accuracy": round(float((pred == labels).mean()), 4), "false_alarms": int((pred & (labels == 0)).sum()),
              "missed": int((~pred & (labels == 1)).sum()), "n": len(labels)}
    for kind in sorted(set(kinds)):
        idx = [i for i, k in enumerate(kinds) if k == kind]
        result[f"recall_{kind}"] = round(float((pred[idx] == labels[idx]).mean()), 3)
    return result


def main():
    torch.manual_seed(0)
    device = "cuda"
    train = DataLoader(Pairs("train", True), BATCH, shuffle=True, num_workers=6, drop_last=True, pin_memory=True)
    val = DataLoader(Pairs("val", False), BATCH, num_workers=4)
    test = DataLoader(Pairs("test", False), BATCH, num_workers=4)
    net = ChangeNet(models.ResNet18_Weights.IMAGENET1K_V1).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, LR, total_steps=EPOCHS * len(train))
    scaler = torch.amp.GradScaler("cuda")
    loss_fn = nn.BCEWithLogitsLoss()
    best, history = -1, []
    for epoch in range(EPOCHS):
        net.train()
        total = 0.0
        for a, b, y, _ in train:
            opt.zero_grad(set_to_none=True)
            with torch.autocast("cuda"):
                loss = loss_fn(net(a.to(device), b.to(device)), y.float().to(device))
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item()
        metrics = evaluate(net, val, device)
        history.append({"epoch": epoch, "loss": round(total / len(train), 4), **metrics})
        print(history[-1], flush=True)
        if metrics["accuracy"] > best:
            best = metrics["accuracy"]
            torch.save(net.state_dict(), OUT / "change_net.pt")
    net.load_state_dict(torch.load(OUT / "change_net.pt", weights_only=True))
    result = {"history": history, "sim_test": evaluate(net, test, device)}
    (OUT / "train_results.json").write_text(json.dumps(result, indent=2))
    print("TEST", result["sim_test"], flush=True)


if __name__ == "__main__":
    main()
