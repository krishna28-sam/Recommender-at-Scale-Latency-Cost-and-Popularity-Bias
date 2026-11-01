"""Download MIND-small without committing raw data; record checksums and terms."""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "manifests"
SOURCES = {
    "MINDsmall_train.zip": [
        "https://mind201910small.blob.core.windows.net/release/MINDsmall_train.zip",
        "https://huggingface.co/datasets/L33/MIND-small/resolve/main/MINDsmall_train.zip",
    ],
    "MINDsmall_dev.zip": [
        "https://mind201910small.blob.core.windows.net/release/MINDsmall_dev.zip",
        "https://huggingface.co/datasets/L33/MIND-small/resolve/main/MINDsmall_dev.zip",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_existing_archive(filename: str):
    for candidate in [RAW / filename, RAW / "_dl" / filename]:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def download_with_fallback(filename: str, urls: list):
    archive = RAW / filename
    existing = find_existing_archive(filename)
    if existing is not None:
        return existing, "local_cache"

    partial = archive.with_suffix(archive.suffix + ".part")
    last_error = None
    for url in urls:
        print(f"Attempting download of {filename} from {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as response, partial.open("wb") as target:
                shutil.copyfileobj(response, target)
            with zipfile.ZipFile(partial) as source:
                bad_member = source.testzip()
                if bad_member is not None:
                    raise ValueError(f"{filename} is corrupt at {bad_member}")
            partial.replace(archive)
            return archive, url
        except Exception as exc:
            print(f"Download failed from {url}: {exc}")
            last_error = exc
            if partial.exists():
                partial.unlink()

    raise RuntimeError(
        f"Failed to download {filename} from both primary Azure and Hugging Face fallback endpoints.\n"
        f"Last error: {last_error}\n"
        f"MANUAL FALLBACK PROCEDURE:\n"
        f"1. Download {filename} directly in your browser from:\n"
        f"   - Primary: {urls[0]}\n"
        f"   - Fallback: {urls[1]}\n"
        f"2. Place the file at: data/raw/{filename}\n"
        f"3. Note: MIND data is governed by Microsoft Research Dataset Terms of Use (non-commercial use)."
    )


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    MANIFEST.mkdir(parents=True, exist_ok=True)
    entries = []
    for filename, urls in SOURCES.items():
        archive, resolved_source = download_with_fallback(filename, urls)
        destination = RAW / archive.stem.replace(".zip", "")
        if not destination.exists():
            print(f"Extracting {archive.name} to {destination}...")
            with zipfile.ZipFile(archive) as source:
                bad_member = source.testzip()
                if bad_member is not None:
                    raise ValueError(f"{filename} is corrupt at {bad_member}")
                source.extractall(destination)
        entries.append({
            "data_source": "real",
            "file": str(archive.relative_to(ROOT)),
            "sha256": sha256(archive),
            "source_url_or_cache": resolved_source,
        })
        print(f"{filename}: sha256={entries[-1]['sha256']}")
    (MANIFEST / "mind-small-checksums.json").write_text(json.dumps(entries, indent=2) + "\n")
    print("Wrote {}".format(MANIFEST / "mind-small-checksums.json"))
    print("Terms: use MIND only under the Microsoft Research Dataset Terms of Use; do not redistribute raw data.")


if __name__ == "__main__":
    main()
