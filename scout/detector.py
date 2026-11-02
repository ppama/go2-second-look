"""Offline before/after change detector, trained only on simulated pairs."""
import numpy as np
import torch
from PIL import Image
from torch import nn
from torchvision import models
from torchvision.transforms import functional as F

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
SIZE = (180, 320)


class ChangeNet(nn.Module):
    def __init__(self, weights=None):
        super().__init__()
        base = models.resnet18(weights=weights)
        self.encoder = nn.Sequential(*list(base.children())[:-2])
        self.head = nn.Sequential(nn.Conv2d(1024, 256, 3, padding=1), nn.ReLU(), nn.AdaptiveMaxPool2d(1), nn.Flatten(), nn.Linear(256, 1))

    def forward(self, a, b):
        fa, fb = self.encoder(a), self.encoder(b)
        return self.head(torch.cat([fa, torch.abs(fa - fb)], dim=1)).squeeze(1)


class Detector:
    backend = "detector"
    calls = 0

    def __init__(self, weights, device="cuda"):
        self.device = device if torch.cuda.is_available() else "cpu"
        self.net = ChangeNet().to(self.device)
        self.net.load_state_dict(torch.load(weights, map_location=self.device, weights_only=True))
        self.net.eval()

    def _tensor(self, frame):
        image = Image.fromarray(np.asarray(frame)).resize(SIZE[::-1], Image.Resampling.BILINEAR)
        return F.normalize(F.to_tensor(image), MEAN, STD).unsqueeze(0).to(self.device)

    @torch.no_grad()
    def compare(self, before, after, name):
        p = torch.sigmoid(self.net(self._tensor(before), self._tensor(after))).item()
        return {"changed": p > 0.5, "hazard": p > 0.5, "changes": [], "summary": f"detector probability {p:.2f}", "probability": round(p, 4)}
