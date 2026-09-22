"""Test first-clone helpers without real credentials or infrastructure access."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_secrets", REPO / "scripts/local-secrets.py")
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        root_patch = patch.object(HELPER, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_initialization_preserves_existing_files_and_symlinks(self):
        inventory = self.root / "inventories/production/group_vars/managed_vms"
        inventory.mkdir(parents=True)
        (inventory / "vault.yml.example").write_text("example\n")
        existing = inventory / "vault.yml"
        existing.write_text("existing encrypted content\n")
        packer = self.root / "packer/ubuntu-24.04"
        packer.mkdir(parents=True)
        (packer / "esxi-8.pkrvars.hcl.example").write_text("example vars\n")
        (inventory / "ssh_keys.yml.example").write_text("example key\n")
        link = inventory / "ssh_keys.yml"
        link.symlink_to(self.root / "missing")
        HELPER.initialize()
        HELPER.initialize()
        self.assertEqual(existing.read_text(), "existing encrypted content\n")
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())
        created = packer / "esxi-8.pkrvars.hcl"
        self.assertEqual(created.read_text(), "example vars\n")
        self.assertEqual(created.stat().st_mode & 0o777, 0o600)

    def test_password_creation_and_preservation(self):
        with patch.object(HELPER.sys.stdin, "isatty", return_value=True), patch.object(
            HELPER.getpass, "getpass", side_effect=["test password", "test password"]
        ):
            HELPER.vaultpass()
        password = self.root / ".vaultpass"
        self.assertEqual(password.read_text(), "test password\n")
        self.assertEqual(password.stat().st_mode & 0o777, 0o600)
        with patch.object(HELPER.getpass, "getpass") as prompt:
            HELPER.vaultpass()
            prompt.assert_not_called()

    def test_mismatched_password_does_not_create_file(self):
        with patch.object(HELPER.sys.stdin, "isatty", return_value=True), patch.object(
            HELPER.getpass, "getpass", side_effect=["first", "second"]
        ), self.assertRaises(SystemExit):
            HELPER.vaultpass()
        self.assertFalse((self.root / ".vaultpass").exists())

    def test_encryption_skips_encrypted_files(self):
        example = self.root / "vault.yml.example"
        example.write_text("example")
        (self.root / "vault.yml").write_text("$ANSIBLE_VAULT;1.1;AES256\ntest\n")
        (self.root / ".vaultpass").write_text("test")
        binary = self.root / ".venv/vmware/bin/ansible-vault"
        binary.parent.mkdir(parents=True)
        binary.touch()
        with patch.object(HELPER, "inventory_examples", return_value=[example]), patch.object(
            HELPER.subprocess, "run"
        ) as run:
            HELPER.encrypt()
            run.assert_not_called()

    @unittest.skipUnless(shutil.which("just"), "just is required for wrapper tests")
    def test_packer_arguments_remain_literal_and_validation_never_builds(self):
        shutil.copyfile(REPO / "justfile", self.root / "justfile")
        wrapper = self.root / "packer/build-ubuntu-vms.sh"
        wrapper.parent.mkdir()
        wrapper.write_text(
            '#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n'
        )
        wrapper.chmod(0o755)
        argument = "VM with spaces; $(touch unwanted).pkrvars.hcl"
        for recipe, suffix in [("packer-validate", ["--validate-only"]), ("packer-build", [])]:
            result = subprocess.run(
                ["just", recipe, "esxi-8", argument], cwd=self.root,
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(result.stdout), ["--target", "esxi-8", argument] + suffix)
        self.assertFalse((self.root / "unwanted").exists())
        result = subprocess.run(["just", "packer-build"], cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
