"""Air manifest / order scenarios: the same shipment is sent in different orders, one phase at a time.
The individual documents of each sample live in samples/<scenario folder>/split/<FJ>/; `fill` puts the documents of ONE phase into
samples/<CASE>/ with a number in front of each file name, so the suite (which sends the files of that folder in name order) sends them
in the order of the phase. The same shipment cannot be in Nexus twice: the user deletes the previous phase's pre-alerts first."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .config import Config

# document types in the order they are sent; a type that the sample does not have (or "House" with several houses) is skipped / expanded
PHASES: dict[str, list[str]] = {
    "manifest": ["Manifest"],
    "house-master": ["House", "Master"],
    "master-house": ["Master", "House", "Manifest", "Invoice", "Packing List", "Certificate of Origin"],
}


def split_dir(cfg: Config, fj: str) -> Path:
    s = cfg.settings["air_manifest_scenarios"]
    return cfg.path(cfg.settings["testsuite"]["samples_dir"]) / s["folder"] / "split" / fj


def _kind(path: Path, fj: str) -> str:
    """'FJ-0002945 - House 2.pdf' -> 'House'; 'FJ-0003067 - Packing List.pdf' -> 'Packing List'."""
    name = re.sub(rf"^{re.escape(fj)}\s*-\s*", "", path.stem)
    return re.sub(r"\s+\d+$", "", name)


def plan(files: list[Path], fj: str, phase: str) -> list[Path]:
    """The files of this sample for the phase, in sending order (several houses stay together, in name order)."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase '{phase}' (choose {', '.join(PHASES)})")
    ordered: list[Path] = []
    for kind in PHASES[phase]:
        ordered += sorted(f for f in files if _kind(f, fj).lower() == kind.lower())
    return ordered


def fill(cfg: Config, case_id: str, phase: str) -> tuple[list[Path], str]:
    """Empties samples/<case>/ (only this staging folder) and loads the phase. Returns (files, problem or '')."""
    sc = cfg.settings["air_manifest_scenarios"]["cases"].get(case_id)
    if not sc:
        return [], f"{case_id} is not an air manifest scenario"
    src = split_dir(cfg, sc["fj"])
    files = sorted(src.glob("*.pdf")) if src.is_dir() else []
    chosen = plan(files, sc["fj"], phase)
    if not chosen:
        return [], f"{case_id} ({sc['fj']}) has no document for phase '{phase}'"
    dest = cfg.path(cfg.settings["testsuite"]["samples_dir"]) / case_id
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*"):
        if old.is_file():
            old.unlink()
    out = []
    for n, f in enumerate(chosen, 1):
        target = dest / f"{n:02d} {f.name}"
        shutil.copy2(f, target)
        out.append(target)
    return out, ""
