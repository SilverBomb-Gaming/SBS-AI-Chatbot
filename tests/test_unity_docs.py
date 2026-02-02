from __future__ import annotations

from pathlib import Path

from knowledge.unity_manual import UnityDocsService


def _write_doc(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_ingest_and_search(tmp_path: Path) -> None:
    project_root = tmp_path
    service = UnityDocsService(project_root)
    source_dir = project_root / "knowledge_sources" / "unity_manual" / "2022LTS"
    sample_text = """
# Lighting Overview
Use the Lighting window to configure baked and realtime lighting.
Adjust the Environment settings for HDRP/URP separately.
"""
    _write_doc(source_dir, "lighting.md", sample_text)
    manifest = service.ingest(source_dir, "2022LTS", chunk_chars=200, overlap_chars=50)
    assert manifest["chunk_count"] >= 1

    result = service.search("lighting window", "2022LTS", pipeline="URP", platform="Windows")
    assert "Unity version: 2022LTS" in result.assumptions
    assert result.citations, "Expected at least one citation"
    assert any("Lighting" in step for step in result.steps)
    assert not result.answer.lower().startswith("insufficient")
