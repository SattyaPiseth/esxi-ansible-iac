"""Verify installer integrity failures preserve the previous executable."""

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location(
    "install_packer", Path(__file__).resolve().parents[1] / "scripts/install-packer.py"
)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class PackerInstallerTests(unittest.TestCase):
    def test_checksum_mismatch_preserves_existing_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "packer"
            destination.write_bytes(b"existing version")
            with patch.object(INSTALLER, "DESTINATION", destination), patch.object(
                INSTALLER, "correct_version", return_value=False
            ), patch.object(INSTALLER.platform, "system", return_value="Linux"), patch.object(
                INSTALLER.platform, "machine", return_value="x86_64"
            ), patch.object(INSTALLER.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")):
                with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
                    INSTALLER.install()
            self.assertEqual(destination.read_bytes(), b"existing version")
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_verified_archive_installs_executable(self):
        archive = io.BytesIO()
        # Exercise checksum streaming across more than one read.
        payload = b"verified binary" * 100_000
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("packer", payload)
        data = archive.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bin/packer"
            with patch.object(INSTALLER, "DESTINATION", destination), patch.object(
                INSTALLER, "correct_version", side_effect=[False, True]
            ), patch.object(INSTALLER.platform, "system", return_value="Linux"), patch.object(
                INSTALLER.platform, "machine", return_value="aarch64"
            ), patch.object(INSTALLER.urllib.request, "urlopen", return_value=io.BytesIO(data)), patch.dict(
                INSTALLER.CHECKSUMS, {"arm64": hashlib.sha256(data).hexdigest()}
            ):
                INSTALLER.install()
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o755)

    def test_matching_version_skips_download(self):
        with patch.object(INSTALLER, "correct_version", return_value=True), patch.object(
            INSTALLER.platform, "system", return_value="Linux"
        ), patch.object(INSTALLER.platform, "machine", return_value="x86_64"), patch.object(
            INSTALLER.urllib.request, "urlopen"
        ) as download:
            INSTALLER.install()
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
