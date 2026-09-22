"""Exercise real playbook conditions with local, harmless module substitutes."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = shutil.which('ansible-playbook') or str(ROOT / '.venv/vmware/bin/ansible-playbook')


class MaintenanceTests(unittest.TestCase):
    def run_play(self, play, inventory, *args):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'play.yml').write_text(yaml.safe_dump([play]))
            (root / 'inventory.yml').write_text(yaml.safe_dump(inventory))
            config = root / 'ansible.cfg'
            config.write_text('[defaults]\nhost_key_checking=False\n')
            result = subprocess.run(
                [ANSIBLE, '-i', str(root / 'inventory.yml'), str(root / 'play.yml'), *args],
                env={**os.environ, 'ANSIBLE_CONFIG': str(config)},
                capture_output=True, text=True, timeout=60,
            )
            return result.returncode, result.stdout + result.stderr

    def test_vm_owner_limits(self):
        inventory = {'all': {'children': {'managed_vm_esxi': {'hosts': {
            'owner': {'esxi_managed_vm_names': ['vm-one']},
            'other': {'esxi_managed_vm_names': ['vm-two']},
        }}}}}
        for filename, prefix in [('04-vm-power.yml', 'vm_power'), ('05-vm-delete.yml', 'vm_delete')]:
            source = yaml.safe_load((ROOT / 'playbooks' / filename).read_text())[0]
            source.pop('roles')
            source['vars'].update({
                'managed_vm_esxi_ownership': {'owner': ['vm-one'], 'other': ['vm-two']},
                'managed_vm_names': ['vm-one', 'vm-two'],
                prefix + '_name': 'vm-one',
            })
            for task in source['tasks']:
                if 'ansible.builtin.include_role' in task:
                    del task['ansible.builtin.include_role']
                    task['ansible.builtin.debug'] = {'msg': 'VM_OPERATION {{ ' + prefix + '_name }}'}
            for limit, success in [('other', False), ('owner', True), ('owner,other', True)]:
                with self.subTest(playbook=filename, limit=limit):
                    code, output = self.run_play(
                        source, inventory, '--limit', limit, '-e', prefix + '_name=vm-one')
                    self.assertEqual(code == 0, success, output)
                    if success:
                        self.assertIn('VM_OPERATION vm-one', output)
                    else:
                        self.assertIn('Include its owning ESXi host', output)
                        self.assertNotIn('VM_OPERATION', output)
            batch = copy.deepcopy(source)
            batch['vars'].update(scope='all', vm_delete_enable_all_confirmation=True,
                                 vm_delete_all_confirmation_phrase='DELETE_ALL_MANAGED_VMS')
            code, output = self.run_play(batch, inventory, '--limit', 'other')
            self.assertEqual(code, 0, output)

    def test_longhorn_disk_previews(self):
        storage = yaml.safe_load((ROOT / 'roles/longhorn_node_prepare/tasks/storage.yml').read_text())
        defaults = yaml.safe_load((ROOT / 'roles/longhorn_node_prepare/defaults/main.yml').read_text())
        for formatted, mounted, allow_format, safe in [
            (False, False, True, True), (True, False, False, True),
            (True, True, False, True), (False, False, False, False),
        ]:
            with self.subTest(formatted=formatted, mounted=mounted, allow_format=allow_format):
                with tempfile.TemporaryDirectory() as directory:
                    data_path = str(Path(directory) / 'data')
                    if mounted:
                        Path(data_path).mkdir()
                    variables = dict(defaults, longhorn_node_prepare_has_data_disk=True,
                                     longhorn_node_prepare_data_device='/dev/mock-data',
                                     longhorn_node_prepare_data_path=data_path,
                                     longhorn_node_prepare_enable_disk_format=allow_format)
                    outputs = {
                        'longhorn_node_prepare_data_device_resolved': '/dev/mock-data',
                        'longhorn_node_prepare_root_source': '/dev/mock-root',
                        'longhorn_node_prepare_root_device_ancestry': '/dev/mock-root',
                        'longhorn_node_prepare_data_device_layout': 'disk',
                        'longhorn_node_prepare_data_device_filesystem': 'ext4' if formatted else '',
                        'longhorn_node_prepare_data_device_mounts': data_path if mounted else '',
                        'longhorn_node_prepare_existing_data_mount': '/dev/mock-data',
                        'longhorn_node_prepare_existing_data_mount_resolved': '/dev/mock-data',
                        'longhorn_node_prepare_data_device_uuid': 'mock-uuid' if formatted else '',
                        'longhorn_node_prepare_data_mount': 'mock-uuid ext4' if mounted else '',
                    }
                    block = copy.deepcopy(storage[-1])

                    def substitute(tasks):
                        for task in tasks:
                            if 'block' in task:
                                substitute(task['block'])
                            if 'ansible.builtin.command' in task:
                                value = outputs[task['register']]
                                task['ansible.builtin.command'] = {
                                    'argv': [sys.executable, '-c', 'print(' + repr(value) + ')']}
                            for module in ['community.general.filesystem', 'ansible.posix.mount']:
                                if module in task:
                                    params = task.pop(module)
                                    task['ansible.builtin.debug'] = {'msg': {module: params}}
                                    task.pop('become', None)
                    substitute([block])
                    play = {'hosts': 'localhost', 'gather_facts': False,
                            'vars': variables, 'tasks': [block]}
                    code, output = self.run_play(play, {'all': {'hosts': {
                        'localhost': {'ansible_connection': 'local', 'ansible_python_interpreter': sys.executable}
                    }}}, '--check')
                    self.assertEqual(code == 0, safe, output)
                    if safe and not formatted:
                        self.assertIn('Would format', output)
                        self.assertNotIn('UUID=mock-uuid', output)
                    if safe and formatted:
                        self.assertIn('UUID=mock-uuid', output)
                    if not safe:
                        self.assertIn('Refusing Longhorn disk preparation', output)
                        self.assertNotIn('Would format', output)

    def test_longhorn_health_preview_before_package_installation(self):
        tasks = yaml.safe_load((ROOT / 'roles/longhorn_node_prepare/tasks/health.yml').read_text())
        outputs = {
            'longhorn_node_prepare_nfs_kernel_config': 'CONFIG_NFS_V4=y\nCONFIG_NFS_V4_1=y',
            'longhorn_node_prepare_mount_propagation': 'shared',
        }
        for task in tasks:
            if 'ansible.builtin.command' in task:
                register = task.get('register')
                code = 'print(' + repr(outputs[register]) + ')' if register in outputs else 'raise SystemExit(99)'
                task['ansible.builtin.command'] = {'argv': [sys.executable, '-c', code]}
        play = {'hosts': 'localhost', 'gather_facts': False,
                'vars': {'longhorn_node_prepare_required_commands': ['not-installed-yet']},
                'tasks': tasks}
        code, output = self.run_play(play, {'all': {'hosts': {
            'localhost': {'ansible_connection': 'local', 'ansible_python_interpreter': sys.executable}
        }}}, '--check')
        self.assertEqual(code, 0, output)
