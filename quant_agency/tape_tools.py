"""Tape rotation / concatenation for the continuous collector.

A continuous run never restarts its engines (feeds, hunter calibration, oracle variance all stay warm); only the *event log* is rotated into numbered part files so memory stays bounded.
Concatenating consecutive parts reproduces the full event stream, which replays through the agency exactly like a single recorded tape.

    python -m quant_agency.tape_tools concat tapes/p10_part0001.npz tapes/p10_part0002.npz --out tapes/p10_full.npz
"""
from __future__ import annotations

import argparse
import json
import os
from typing import List

import numpy as np


def part_path(stem: str, k: int) -> str:
    stem = stem[:-4] if stem.endswith(".npz") else stem
    return f"{stem}_part{k:04d}.npz"


def rotate_tape(ag, stem: str, k: int, extra: dict) -> str:
    """Write the agency's accumulated event log as part ``k`` and start an empty one. Engines are untouched."""
    path = part_path(stem, k)
    ag.save_tape(path, extra=extra)
    ag.start_recording()
    return path


def concat_tapes(paths: List[str], out: str) -> int:
    parts = [np.load(p) for p in paths]
    keys = ("t", "i", "b", "a", "bq", "aq")
    cat = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    if (np.diff(cat["t"]) < 0).any():
        raise ValueError("parts are not in time order")
    np.savez_compressed(out, **cat, metas=parts[0]["metas"], extra=parts[0]["extra"])
    return int(cat["t"].size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["concat"])
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(f"{a.out}: {concat_tapes(sorted(a.parts), a.out)} events")


if __name__ == "__main__":
    main()
