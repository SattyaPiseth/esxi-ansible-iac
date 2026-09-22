#!/usr/bin/env python3
"""Install the qualified Packer version locally, without sudo or shell changes."""

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

VERSION = "1.16.1"
# https://releases.hashicorp.com/packer/1.16.1/packer_1.16.1_SHA256SUMS
CHECKSUMS = {
    "amd64": "af38a9e93e4ed1b9ca68206ae969c64c300c82a3dde46a780dfa629f0867f651",
    "arm64": "4784ac0b9228a61f3ecb3861dbf0bf9ebeab6ddb0f5a10466126b8daa5db0de5",
}
DESTINATION = Path(__file__).resolve().parents[1] / ".venv/vmware/bin/packer"


def correct_version(binary):
    try:
        result = subprocess.run(
            [str(binary), "version"], capture_output=True, text=True, check=True,
            timeout=30,
        )
        return result.stdout.splitlines()[0] == f"Packer v{VERSION}"
    except (OSError, subprocess.SubprocessError, IndexError):
        return False


def install():
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if platform.system() != "Linux" or architecture not in CHECKSUMS:
        raise SystemExit("Packer bootstrap supports Linux x86_64 and aarch64 control nodes.")
    if correct_version(DESTINATION):
        print(f"Packer {VERSION} is already installed at {DESTINATION}")
        return
    filename = f"packer_{VERSION}_linux_{architecture}.zip"
    url = f"https://releases.hashicorp.com/packer/{VERSION}/{filename}"
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DESTINATION.parent) as directory:
        archive = Path(directory) / filename
        print(f"Downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        # Stream the checksum using APIs available on Python 3.10.
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != CHECKSUMS[architecture]:
            raise SystemExit("Packer archive checksum mismatch; existing installation preserved.")
        binary = Path(directory) / "packer"
        with zipfile.ZipFile(archive) as package, package.open("packer") as source, binary.open("wb") as stream:
            shutil.copyfileobj(source, stream)
        binary.chmod(0o755)
        if not correct_version(binary):
            raise SystemExit("Downloaded Packer failed version verification; existing installation preserved.")
        os.replace(binary, DESTINATION)
    print(f"Installed Packer {VERSION} at {DESTINATION}")


if __name__ == "__main__":
    install()
