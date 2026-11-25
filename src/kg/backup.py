"""Copy data/labels/ to a dated folder outside the repository.

data/labels/ is not in git (the English pilot files have no license, and the
sheets quote them), and it was lost once. Every script that writes label sheets
calls backup_labels() first; `kg backup-labels` runs it by hand.

The backup folder is KG_LABEL_BACKUP_DIR if set, else ~/kg_label_backups.
Only file names and counts are printed, never file contents.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ENV_VAR = "KG_LABEL_BACKUP_DIR"


def backup_root() -> Path:
    value = os.environ.get(ENV_VAR)
    return Path(value) if value else Path.home() / "kg_label_backups"


def backup_labels(labels: Path, root: Path | None = None,
                  now: datetime | None = None) -> Path | None:
    """Copy `labels` to <root>/labels-YYYYMMDD-HHMMSS. Returns the new folder,
    or None when there is nothing to back up. Never overwrites a backup."""
    if not labels.is_dir() or not any(labels.iterdir()):
        return None
    root = root or backup_root()
    root = root.resolve()
    if root == labels.resolve() or root.is_relative_to(labels.resolve()):
        raise ValueError("backup folder must be outside the labels folder")
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    dest = root / f"labels-{stamp}"
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"labels-{stamp}-{n}"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(labels, dest)
    return dest
