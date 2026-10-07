"""Explicit download of one pinned public model; never called by the application.

Only safetensors weights and a fixed allowlist of configuration/tokenizer files.
The output directory must not exist. Downloads go to a temporary staging directory;
only a complete snapshot is published. No user documents are sent.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
FILES = (
    "README.md",
    "1_Pooling/config.json",
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def download(destination: Path) -> dict[str, object]:
    from huggingface_hub import hf_hub_download

    if destination.exists():
        raise ValueError("Destination already exists; do not overwrite a model snapshot")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-download-", dir=destination.parent) as temp:
        staging = Path(temp) / "snapshot"
        staging.mkdir()
        checksums = {}
        for filename in FILES:
            print(f"Downloading {filename}", flush=True)
            cached = hf_hub_download(
                repo_id=MODEL,
                revision=REVISION,
                filename=filename,
                cache_dir=str(Path(temp) / "cache"),
                token=False,
            )
            target = staging / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, target)
            with target.open("rb") as stream:
                checksums[filename] = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {"repository": MODEL, "revision": REVISION, "sha256": checksums}
        (staging / "snapshot.json").write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        staging.rename(destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(download(args.destination.resolve()), indent=2))


if __name__ == "__main__":
    main()
