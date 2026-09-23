"""Validate recipe routing without contacting ESXi."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('just'), 'just is required')
class ValidateShortcutTests(unittest.TestCase):
    def test_shared_arguments_live_facts_and_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'justfile', root / 'justfile')
            binary = root / '.venv/vmware/bin/ansible-playbook'
            binary.parent.mkdir(parents=True)
            binary.write_text(
                '#!/usr/bin/env python3\n'
                'import json, os, sys\n'
                'from pathlib import Path\n'
                'with open("calls.jsonl", "a") as stream:\n'
                '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                'count = len(Path("calls.jsonl").read_text().splitlines())\n'
                'sys.exit(2 if count == int(os.environ["FAIL_CALL"]) else 0)\n'
            )
            binary.chmod(0o755)
            arguments = ['-i', 'alternate inventory.yml', '--limit', 'selected-host',
                         '-e', '{"literal": "$(touch injected)"}']
            expected = [
                ['playbooks/01-esxi-facts.yml', '--list-hosts', *arguments],
                ['playbooks/99-site-run.yml', '--syntax-check', *arguments],
                ['playbooks/01-esxi-facts.yml', *arguments],
            ]
            for failure, count in [(0, 3), (1, 1), (2, 2), (3, 3)]:
                with self.subTest(failure=failure):
                    log = root / 'calls.jsonl'
                    log.unlink(missing_ok=True)
                    result = subprocess.run(
                        ['just', 'validate', *arguments], cwd=root,
                        env={**os.environ, 'FAIL_CALL': str(failure)}, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode == 0, not failure, result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual(calls, expected[:count])
                    self.assertFalse((root / 'injected').exists())
