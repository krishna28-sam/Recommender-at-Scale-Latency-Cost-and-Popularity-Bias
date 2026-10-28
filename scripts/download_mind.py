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
    "MINDsmall_train.zip": "https://mind201910small.blob.core.windows.net/release/MINDsmall_train.zip",
    "MINDsmall_dev.zip": "https://mind201910small.blob.core.windows.net/release/MINDsmall_dev.zip",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    MANIFEST.mkdir(parents=True, exist_ok=True)
    entries = []
    for filename, url in SOURCES.items():
        archive = RAW / filename
        if not archive.exists():
            partial = archive.with_suffix(archive.suffix + ".part")
            print("Downloading {} from {}".format(filename, url))
            with urllib.request.urlopen(url) as response, partial.open("wb") as target:
                shutil.copyfileobj(response, target)
            with zipfile.ZipFile(partial) as source:
                bad_member = source.testzip()
                if bad_member is not None:
                    raise ValueError("{} is corrupt at {}".format(filename, bad_member))
            partial.replace(archive)
        destination = RAW / archive.stem
        if not destination.exists():
            with zipfile.ZipFile(archive) as source:
                bad_member = source.testzip()
                if bad_member is not None:
                    raise ValueError("{} is corrupt at {}".format(filename, bad_member))
                source.extractall(destination)
        entries.append({"data_source": "real", "file": str(archive.relative_to(ROOT)),
                        "sha256": sha256(archive), "url": url})
        print("{}: sha256={}".format(filename, entries[-1]["sha256"]))
    (MANIFEST / "mind-small-checksums.json").write_text(json.dumps(entries, indent=2) + "\n")
    print("Wrote {}".format(MANIFEST / "mind-small-checksums.json"))
    print("Terms: use MIND only under the Microsoft Research Dataset Terms of Use; do not redistribute raw data.")


if __name__ == "__main__":
    main()
