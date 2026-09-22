"""Check deletion wrapper guards without contacting ESXi."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("just"), "just is required")
class DeleteShortcutTests(unittest.TestCase):
    def test_confirmation_and_literal_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "justfile", root / "justfile")
            stub = root / ".venv/vmware/bin/ansible-playbook"
            stub.parent.mkdir(parents=True)
            stub.write_text(
                '#!/usr/bin/env python3\nimport json, sys\n'
                'from pathlib import Path\n'
                'Path("invoked").touch()\nprint(json.dumps(sys.argv[1:]))\n'
            )
            stub.chmod(0o755)
            for arguments in [[], ["vm"], ["vm", "other"], ["", ""]]:
                result = subprocess.run(
                    ["just", "vm-delete", *arguments], cwd=root, capture_output=True
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "invoked").exists())
            name = 'VM with spaces; $(touch injected)'
            result = subprocess.run(
                ["just", "vm-delete", name, name, "--check", "--limit", "vm_esxi_8.0"],
                cwd=root, capture_output=True, text=True, check=True,
            )
            arguments = json.loads(result.stdout)
            self.assertEqual(arguments[:-2], [
                "playbooks/05-vm-delete.yml", "--check", "--limit", "vm_esxi_8.0"
            ])
            self.assertEqual(arguments[-2], "--extra-vars")
            self.assertEqual(json.loads(arguments[-1]), {
                "scope": "single", "vm_delete_name": name,
                "vm_delete_confirm": True, "vm_delete_confirm_name": name,
            })
            self.assertFalse((root / "injected").exists())
