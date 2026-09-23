#!/usr/bin/env python3
"""Restore local client artifacts from an explicitly trusted SSH source."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(argv, **kwargs):
    try:
        return subprocess.run(argv, check=True, timeout=180, stderr=subprocess.DEVNULL, **kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Client setup failed during {Path(argv[0]).name}; check connectivity, permissions, and source files.") from error


def setup(source, source_dir, cluster='production', identity=None):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', source):
        raise SystemExit('Use an SSH host alias or user@hostname, without SSH options or a path.')
    if not source_dir.startswith('/') or '\n' in source_dir or '\r' in source_dir:
        raise SystemExit('The source artifacts directory must be an absolute remote path.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', cluster):
        raise SystemExit('Cluster name must contain only letters, numbers, underscores, and hyphens.')
    destination = ROOT / '.generated/kubespray' / cluster / 'artifacts'
    if any(parent.is_symlink() for parent in [destination, *destination.parents]):
        raise SystemExit('Refusing a destination with symlinked path components.')
    if any(os.path.lexists(destination / name) for name in ('kubectl', 'admin.conf')):
        raise SystemExit('Existing client artifacts preserved. Back up and move both files before restoring a replacement pair.')
    ssh = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes',
           '-o', 'ConnectTimeout=15']
    if identity:
        ssh += ['-i', identity]
    ssh += [source]
    remote = run(ssh + ['uname -s; uname -m'], capture_output=True, text=True).stdout.splitlines()
    if remote != [platform.system(), platform.machine()]:
        raise SystemExit('Source and destination OS/architecture differ; use a compatible client binary.')
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise SystemExit('Client setup supports Linux x86_64 and aarch64.')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='.client-setup-', dir=destination) as directory:
        staging = Path(directory)
        for name in ('kubectl', 'admin.conf'):
            path = staging / name
            with path.open('xb') as output:
                path.chmod(0o600)
                run(ssh + ['cat -- ' + shlex.quote(source_dir.rstrip('/') + '/' + name)], stdout=output)
            if path.stat().st_size == 0:
                raise SystemExit(f'Empty source {name}; no artifacts installed.')
        binary = staging / 'kubectl'
        with binary.open('rb') as stream:
            header = stream.read(20)
        machine = 62 if platform.machine() == 'x86_64' else 183
        if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != machine:
            raise SystemExit('Downloaded kubectl is not a compatible Linux executable.')
        binary.chmod(0o755)
        run([str(binary), 'version', '--client'], capture_output=True)
        result = run([str(binary), '--kubeconfig', str(staging / 'admin.conf'),
                      'config', 'view', '-o', 'json'], capture_output=True, text=True)
        try:
            config = json.loads(result.stdout)
            if not config.get('current-context') or not config.get('clusters') or not config.get('users'):
                raise ValueError('Missing current context, cluster, or user')
            contexts = {entry['name']: entry['context'] for entry in config.get('contexts', [])}
            current = contexts[config['current-context']]
            if (current.get('cluster') not in {entry['name'] for entry in config['clusters']}
                    or current.get('user') not in {entry['name'] for entry in config['users']}):
                raise ValueError('Unresolved current context')
            for cluster_entry in config['clusters']:
                settings = cluster_entry['cluster']
                if not settings.get('server') or settings.get('certificate-authority'):
                    raise ValueError('Missing server or external CA file')
            for user in config['users']:
                if any(key in user['user'] for key in ('client-certificate', 'client-key', 'tokenFile', 'exec', 'auth-provider')):
                    raise ValueError('External credential dependency')
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise SystemExit('Use a self-contained kubeconfig with a valid current context and embedded credentials; no files installed.') from error
        # Exclusive hard links publish verified files without overwriting a racing writer.
        installed = []
        try:
            for name in ('kubectl', 'admin.conf'):
                target = destination / name
                os.link(staging / name, target)
                installed.append(target)
        except OSError:
            for target in installed:
                target.unlink()
            raise SystemExit('Could not install the artifact pair; existing destination files were preserved.')
    print(f'Installed verified client artifacts in {destination}.')
    print('No API requests were made. Verify the intended cluster, then run just kubernetes-health.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Explicit trusted SSH host alias or user@hostname')
    parser.add_argument('source_dir', help='Absolute remote directory containing kubectl and admin.conf')
    parser.add_argument('--cluster', default='production', help='Local artifact directory cluster name')
    parser.add_argument('--identity', help='SSH private key path; normal SSH config also applies')
    args = parser.parse_args()
    setup(args.source, args.source_dir, args.cluster, args.identity)


if __name__ == '__main__':
    main()
