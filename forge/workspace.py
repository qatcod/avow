from __future__ import annotations

import shutil
from pathlib import Path


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.solution_dir = self.root / "solution"
        self.root.mkdir(parents=True, exist_ok=True)

    def seed_from(self, best: Path | None) -> None:
        if self.solution_dir.exists():
            shutil.rmtree(self.solution_dir)
        if best is not None and Path(best).is_dir():
            shutil.copytree(best, self.solution_dir)
        else:
            self.solution_dir.mkdir(parents=True)

    def promote_to(self, best: Path) -> None:
        best = Path(best)
        if best.exists():
            shutil.rmtree(best)
        shutil.copytree(self.solution_dir, best)
