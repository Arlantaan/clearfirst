#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
WORLD_ROOT = Path(__file__).resolve().parent
DOCUMENT_SUFFIXES = {".jpg", ".jpeg", ".pdf", ".png"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_checked(source: Path, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(source) != sha256(destination):
            raise RuntimeError(f"refusing to overwrite different file: {destination}")
        return False
    shutil.copy2(source, destination)
    return True


def release(agent: Path) -> int:
    if not (agent / "helper").is_file():
        raise RuntimeError(f"not an agent workspace: {agent}")

    released = 0
    for source in sorted((WORLD_ROOT / "follow_up").iterdir()):
        if not source.is_file() or source.suffix.lower() not in DOCUMENT_SUFFIXES:
            continue
        released += copy_checked(source, agent / "workspace/inbox" / source.name)

    pages = WORLD_ROOT / "follow_up/pages"
    if pages.is_dir():
        for source in sorted(pages.glob("*.png")):
            copy_checked(source, agent / "workspace/inbox/pages" / source.name)

    return released


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent",
        type=Path,
        default=KIT_ROOT / "agent",
        help="participant agent directory",
    )
    args = parser.parse_args()
    agent = args.agent.resolve()
    released = release(agent)
    print(f"Released {released} follow-up documents into {agent}")


if __name__ == "__main__":
    main()
