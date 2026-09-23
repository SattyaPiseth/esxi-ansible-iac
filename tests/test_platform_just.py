"""Exercise platform recipe routing without running Ansible or infrastructure."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('just'), 'just is required')
class PlatformShortcutTests(unittest.TestCase):
    def test_routing_literal_arguments_and_failures(self):
        routes = {
            'kubernetes-inventory': '07-kubespray-inventory.yml',
            'kubernetes-install': '08-kubespray-install.yml',
            'kubernetes-prepare': '10-kubernetes-node-prepare.yml',
            'kubernetes-deploy': '09-kubespray-deploy.yml',
            'kubernetes-metallb': '13-kubespray-metallb.yml',
            'kubernetes-health': '14-kubernetes-health.yml',
            'longhorn-prepare': '16-longhorn-node-prepare.yml',
            'argocd-bootstrap': '19-argocd-bootstrap.yml',
        }
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(repo / 'justfile', root / 'justfile')
            binary = root / '.venv/vmware/bin/ansible-playbook'
            binary.parent.mkdir(parents=True)
            binary.write_text(
                '#!/usr/bin/env python3\nimport json, os, sys\n'
                'print(json.dumps(sys.argv[1:]))\n'
                'sys.exit(int(os.environ.get("STUB_EXIT", "0")))\n'
            )
            binary.chmod(0o755)
            options = ['-i', 'inventory with spaces.yml', '--check', '--limit', 'worker',
                       '-e', '{"literal":"$(touch injected)","argocd_bootstrap_enable":false}']
            for recipe, playbook in routes.items():
                self.assertTrue((repo / 'playbooks' / playbook).is_file())
                for args, status in [([], 0), (options, 0), (options, 2)]:
                    with self.subTest(recipe=recipe, args=args, status=status):
                        result = subprocess.run(
                            ['just', recipe, *args], cwd=root, capture_output=True, text=True,
                            env={**os.environ, 'STUB_EXIT': str(status)},
                        )
                        self.assertEqual(json.loads(result.stdout), ['playbooks/' + playbook, *args])
                        self.assertEqual(result.returncode == 0, status == 0, result.stderr)
                        self.assertFalse((root / 'injected').exists())
