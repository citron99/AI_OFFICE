import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def downloader():
    path = Path(__file__).resolve().parents[2] / "scripts" / "download_semantic_model.py"
    spec = importlib.util.spec_from_file_location("model_download_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_pinned_complete_and_never_overwrites(tmp_path: Path, monkeypatch) -> None:
    module = downloader()
    source = tmp_path / "fake"
    source.write_bytes(b"fixture")
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        assert kwargs["revision"] == module.REVISION
        assert kwargs["token"] is False
        return str(source)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=fetch))
    destination = tmp_path / "model"
    manifest = module.download(destination)
    assert set(manifest["sha256"]) == set(module.FILES)
    assert (destination / "snapshot.json").is_file()
    assert not any(p.is_symlink() for p in destination.rglob("*"))
    with pytest.raises(ValueError, match="already exists"):
        module.download(destination)
    assert len(calls) == len(module.FILES)


def test_failed_download_never_publishes_snapshot(tmp_path: Path, monkeypatch) -> None:
    def fail(**kwargs):
        raise OSError("offline")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=fail))
    destination = tmp_path / "model"
    with pytest.raises(OSError):
        downloader().download(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".model-download-*"))
