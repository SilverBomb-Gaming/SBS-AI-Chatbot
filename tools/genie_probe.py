#!/usr/bin/env python3
"""Lightweight inspector for GENIE Hugging Face drops."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_safetensors_header(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("rb") as handle:
        header_len_bytes = handle.read(8)
        if len(header_len_bytes) != 8:
            raise RuntimeError("Invalid safetensors file: truncated header length")
        header_len = int.from_bytes(header_len_bytes, byteorder="little", signed=False)
        header_bytes = handle.read(header_len)
        if len(header_bytes) != header_len:
            raise RuntimeError("Invalid safetensors file: truncated header payload")
    return json.loads(header_bytes.decode("utf-8"))


def _iter_tensor_summaries(header: Dict[str, Any]) -> Iterable[Tuple[str, str, Iterable[int]]]:
    for name, info in header.items():
        if name == "__metadata__":
            continue
        dtype = info.get("dtype", "?")
        shape = info.get("shape", [])
        yield name, dtype, shape


def _print_config(config: Dict[str, Any]) -> None:
    print("CONFIG SUMMARY")
    for key in sorted(config):
        print(f"  {key}: {config[key]}")


def _print_tensors(summary: Iterable[Tuple[str, str, Iterable[int]]], *, limit: int) -> None:
    rows = list(summary)
    print(f"\nTENSOR HEADER SUMMARY (total={len(rows)})")
    for idx, (name, dtype, shape) in enumerate(rows):
        if idx >= limit:
            remaining = len(rows) - limit
            print(f"  ... ({remaining} more tensors) ...")
            break
        dims = "x".join(str(dim) for dim in shape)
        print(f"  {name}: dtype={dtype} shape=[{dims}]")
    embed_like = [name for name, _, _ in rows if "embed" in name.lower()]
    if embed_like:
        print("\nEMBEDDING-LIKE PARAMETERS")
        for name in embed_like[:10]:
            print(f"  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect GENIE config and safetensors headers without heavy loading.")
    parser.add_argument("repo_dir", type=Path, help="Path to the local Hugging Face snapshot (e.g., GENIE_210M_v0)")
    parser.add_argument(
        "--weights-name",
        default="model.safetensors",
        help="Weights filename inside the repo directory (default: model.safetensors)",
    )
    parser.add_argument(
        "--tensor-limit",
        type=int,
        default=25,
        help="Maximum number of tensor rows to print (default: 25)",
    )
    args = parser.parse_args()

    repo_dir = args.repo_dir.expanduser().resolve()
    config_path = repo_dir / "config.json"
    weights_path = repo_dir / args.weights_name

    print(f"Repo: {repo_dir}")
    print(f"Config: {config_path}")
    print(f"Weights: {weights_path}")

    config = _read_json(config_path)
    _print_config(config)

    header = _read_safetensors_header(weights_path)
    _print_tensors(_iter_tensor_summaries(header), limit=max(1, args.tensor_limit))


if __name__ == "__main__":
    main()
