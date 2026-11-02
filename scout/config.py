from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    with open(path or ROOT / "configs" / "mission.yaml") as f:
        return yaml.safe_load(f)
