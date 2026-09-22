#!/usr/bin/env python3
"""Initialize ignored operator files without overwriting existing credentials."""

import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def create_private(path, content):
    """Create exclusively with mode 0600, including when a symlink exists."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Preserved {path.relative_to(ROOT)}")
        return
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
    print(f"Created {path.relative_to(ROOT)}")


def inventory_examples():
    inventory = ROOT / "inventories/production"
    return sorted(inventory.rglob("vault.yml.example")) + sorted(
        inventory.rglob("ssh_keys.yml.example")
    )


def initialize():
    examples = inventory_examples() + sorted(
        (ROOT / "packer/ubuntu-24.04").rglob("*.pkrvars.hcl.example")
    )
    for example in examples:
        create_private(example.with_suffix(""), example.read_text())
    print("Edit copied placeholders before encryption or builds. Keep only intended VM variable files.")


def vaultpass():
    path = ROOT / ".vaultpass"
    if os.path.lexists(path):
        print("Preserved existing .vaultpass")
        return
    if not sys.stdin.isatty():
        raise SystemExit("Run just vaultpass in an interactive terminal; passwords are not accepted as arguments.")
    password = getpass.getpass("Vault password (use the existing password for existing vaults): ")
    confirmation = getpass.getpass("Confirm Vault password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords must be non-empty and match; no file created.")
    create_private(path, password + "\n")


def encrypt():
    executable = ROOT / ".venv/vmware/bin/ansible-vault"
    if not executable.is_file():
        raise SystemExit("Run just deps first.")
    if not (ROOT / ".vaultpass").is_file():
        raise SystemExit("Run just vaultpass first.")
    paths = [example.with_suffix("") for example in inventory_examples()]
    if any(not path.is_file() for path in paths):
        raise SystemExit("Missing local inventory files; run just secrets-init and edit the placeholders first.")
    for path in paths:
        if path.is_symlink():
            raise SystemExit(f"Refusing to encrypt symlink: {path.relative_to(ROOT)}")
    for path in paths:
        if path.read_bytes().startswith(b"$ANSIBLE_VAULT;"):
            print(f"Already encrypted: {path.relative_to(ROOT)}")
            continue
        subprocess.run([str(executable), "encrypt", str(path)], cwd=ROOT, check=True)
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "vaultpass", "encrypt"))
    action = parser.parse_args().action
    {"init": initialize, "vaultpass": vaultpass, "encrypt": encrypt}[action]()


if __name__ == "__main__":
    main()
