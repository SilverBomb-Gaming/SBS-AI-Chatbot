#!/usr/bin/env python3
"""CLI helper to ingest Unity manual exports for offline RAG."""
from __future__ import annotations

import argparse
from pathlib import Path

from knowledge.unity_manual import UnityDocsService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index a local Unity manual snapshot for grounded retrieval.")
    parser.add_argument("source_dir", type=Path, help="Path to the Unity docs directory (HTML/Markdown export).")
    parser.add_argument("version", help="Version tag, e.g., 2022LTS or Unity6.")
    parser.add_argument("--chunk-chars", type=int, default=1200, help="Chunk size in characters (default: 1200).")
    parser.add_argument("--overlap-chars", type=int, default=200, help="Character overlap between chunks (default: 200).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = UnityDocsService(Path.cwd())
    manifest = service.ingest(
        args.source_dir,
        args.version,
        chunk_chars=max(400, args.chunk_chars),
        overlap_chars=max(40, args.overlap_chars),
    )
    print("Indexed Unity docs:")
    for key, value in manifest.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
