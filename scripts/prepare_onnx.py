"""Download the pinned lightweight model once, preferably during image build."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.clip_assets import COMMON_FILES, MODEL_FILES, ONNX_REPO, ONNX_REVISION, Q8_BUILD_ID


def prepare(destination: Path, precision="q8f16", source_directory=None) -> None:
    if precision == "q8f16" and any(not (destination / name).is_file() for name in MODEL_FILES[precision]):
        source_directory = source_directory or destination / ".source"
        prepare(source_directory, "fp16")
        from build_q8 import build
        build(source_directory / "onnx", destination / "onnx")
    manifest = {"repository": ONNX_REPO, "revision": ONNX_REVISION, "files": {}}
    manifest["precision"] = precision
    if precision == "q8f16":
        manifest["conversion"] = Q8_BUILD_ID
    for filename in MODEL_FILES[precision] + COMMON_FILES:
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            print(f"Downloading {filename}", flush=True)
            request = urllib.request.Request(
                f"https://huggingface.co/{ONNX_REPO}/resolve/{ONNX_REVISION}/{filename}",
                headers={"User-Agent": "VisionText-model-preparation/1.0"},
            )
            temporary = target.with_suffix(target.suffix + ".part")
            with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            temporary.replace(target)
        digest = hashlib.sha256()
        with target.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        manifest["files"][filename] = {"bytes": target.stat().st_size, "sha256": digest.hexdigest()}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("model_cache/onnx"))
    parser.add_argument("--precision", choices=MODEL_FILES, default="q8f16")
    parser.add_argument("--source-directory", type=Path)
    args = parser.parse_args()
    prepare(args.directory, args.precision, args.source_directory)
