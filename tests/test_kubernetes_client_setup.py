"""Client restoration tests use mock SSH transfers and synthetic credentials."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('client_setup', ROOT / 'scripts/setup-kubernetes-client.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class ClientSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.destination = self.root / '.generated/kubespray/production/artifacts'
        self.config = {'current-context': 'test', 'clusters': [{'name': 'cluster', 'cluster': {'server': 'https://example.invalid'}}],
                       'contexts': [{'name': 'test', 'context': {'cluster': 'cluster', 'user': 'operator'}}],
                       'users': [{'name': 'operator', 'user': {'token': 'synthetic'}}]}
        self.commands = []
        self.bad_binary = False
        self.fail_transfer = False
        self.remote_arch = 'x86_64'
        for target, value in [('ROOT', self.root), ('platform.system', 'Linux'), ('platform.machine', 'x86_64')]:
            mock = patch.object(HELPER, target, value) if target == 'ROOT' else patch(
                'platform.' + target.split('.')[1], return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(HELPER.subprocess, 'run', side_effect=self.run_mock)
        mock.start()
        self.addCleanup(mock.stop)

    def run_mock(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[0] == 'ssh':
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('-T', argv)
            self.assertIn('ForwardAgent=no', argv)
            self.assertIn('ClearAllForwardings=yes', argv)
            if argv[-1].startswith('uname'):
                return subprocess.CompletedProcess(argv, 0, 'Linux\n' + self.remote_arch + '\n')
            if argv[-1].endswith('admin.conf\'') or argv[-1].endswith('admin.conf'):
                if self.fail_transfer:
                    raise subprocess.CalledProcessError(1, argv)
                kwargs['stdout'].write(b'synthetic kubeconfig')
            else:
                header = bytearray(20)
                header[:6] = b'\x7fELF\x02\x01'
                header[18:20] = (62).to_bytes(2, 'little')
                kwargs['stdout'].write(b'invalid' if self.bad_binary else header)
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, 0, json.dumps(self.config))

    def test_private_pair_and_quoted_remote_paths(self):
        HELPER.setup('operator@host', '/trusted path/$(literal)', identity='/key with spaces')
        self.assertEqual((self.destination / 'kubectl').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.destination / 'admin.conf').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertIn("cat -- '/trusted path/$(literal)/admin.conf'", self.commands[2])
        self.assertFalse(list(self.destination.glob('.client-setup-*')))

    def test_existing_and_dangling_symlink_preserved_without_ssh(self):
        self.destination.mkdir(parents=True)
        target = self.destination / 'admin.conf'
        target.symlink_to(self.root / 'missing')
        with self.assertRaises(SystemExit):
            HELPER.setup('host', '/artifacts')
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.commands, [])

    def test_transfer_compatibility_and_config_failures_install_nothing(self):
        for failure in ['transfer', 'architecture', 'binary', 'config']:
            with self.subTest(failure=failure):
                self.fail_transfer = failure == 'transfer'
                self.remote_arch = 'aarch64' if failure == 'architecture' else 'x86_64'
                self.bad_binary = failure == 'binary'
                self.config['users'][0]['user'] = {'exec': {}} if failure == 'config' else {'token': 'synthetic'}
                with self.assertRaises(SystemExit):
                    HELPER.setup('host', '/artifacts')
                self.assertFalse((self.destination / 'kubectl').exists())
                self.assertFalse((self.destination / 'admin.conf').exists())
                self.assertFalse(list(self.destination.glob('.client-setup-*')))

    def test_inactive_credential_plugins_and_broken_context_rejected(self):
        self.config['users'].append({'name': 'unused', 'user': {'exec': {'command': 'untrusted'}}})
        with self.assertRaises(SystemExit):
            HELPER.setup('host', '/artifacts')
        self.assertFalse((self.destination / 'admin.conf').exists())
        self.config['users'].pop()
        self.config['contexts'][0]['context']['cluster'] = 'missing'
        with self.assertRaises(SystemExit):
            HELPER.setup('host', '/artifacts')
        self.assertFalse((self.destination / 'admin.conf').exists())

    def test_second_publish_failure_rolls_back_first_file(self):
        original_link = os.link

        def competing_writer(source, target):
            if Path(target).name == 'admin.conf':
                Path(target).write_text('existing credentials')
                raise FileExistsError('competing writer')
            original_link(source, target)

        with patch.object(HELPER.os, 'link', side_effect=competing_writer):
            with self.assertRaises(SystemExit):
                HELPER.setup('host', '/artifacts')
        self.assertFalse((self.destination / 'kubectl').exists())
        self.assertEqual((self.destination / 'admin.conf').read_text(), 'existing credentials')

    def test_invalid_inputs_never_contact_ssh(self):
        for source, path, cluster in [('-option', '/safe', 'production'),
                                      ('host', '~/relative', 'production'),
                                      ('host', '/safe', '../escape')]:
            with self.assertRaises(SystemExit):
                HELPER.setup(source, path, cluster)
        self.assertEqual(self.commands, [])


@unittest.skipUnless(shutil.which('just'), 'just is required')
class ClientRecipeTests(unittest.TestCase):
    def test_explicit_arguments_are_forwarded_literally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / 'justfile', root / 'justfile')
            script = root / 'scripts/setup-kubernetes-client.py'
            script.parent.mkdir()
            script.write_text('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            args = ['operator@host', '/path with spaces/$(touch injected)', '--cluster', 'lab']
            result = subprocess.run(['just', 'kubernetes-client-setup', *args], cwd=root,
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), args)
            self.assertFalse((root / 'injected').exists())
            result = subprocess.run(['just', 'kubernetes-client-setup'], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)


class HealthArtifactTests(unittest.TestCase):
    def test_custom_binary_name_and_symlink_permissions(self):
        import yaml

        ansible = ROOT / '.venv/vmware/bin/ansible-playbook'
        if not ansible.exists():
            found = shutil.which('ansible-playbook')
            if not found:
                self.skipTest('ansible-playbook is required')
            ansible = Path(found)
        tasks = yaml.safe_load((ROOT / 'roles/kubernetes_health/tasks/artifacts.yml').read_text())[:2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'custom-client'
            binary.write_text('#!/bin/sh\nexit 0\n')
            link = root / 'client-link'
            link.symlink_to(binary)
            config = root / 'operator-config'
            config.write_text('synthetic')
            config.chmod(0o600)
            play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': {
                'kubernetes_health_kubectl': str(link),
                'kubernetes_health_kubeconfig': str(config),
            }, 'tasks': tasks}]
            path = root / 'play.yml'
            path.write_text(yaml.safe_dump(play))
            settings = root / 'ansible.cfg'
            settings.write_text('[defaults]\n')
            for mode, success in [(0o755, True), (0o644, False)]:
                with self.subTest(mode=mode):
                    binary.chmod(mode)
                    result = subprocess.run(
                        [str(ansible), '-i', 'localhost,', '-c', 'local', str(path)],
                        env={**os.environ, 'ANSIBLE_CONFIG': str(settings)},
                        capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
