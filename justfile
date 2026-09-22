# Compatible with Ubuntu 24.04's just 1.21.
set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments
export PATH := justfile_directory() + "/.venv/vmware/bin:" + env_var("PATH")

# Show available project commands.
default:
    @just --list

# Install Packer, pinned Python tools, and Ansible collections.
deps: packer-install
    python3 -m venv .venv/vmware
    .venv/vmware/bin/python -m pip install --upgrade pip
    .venv/vmware/bin/python -m pip install -r requirements-dev.txt
    .venv/vmware/bin/ansible-galaxy collection install -r requirements.yml

# Install checksum-verified Packer 1.16.1 locally (no sudo required).
packer-install:
    @python3 scripts/install-packer.py

# Copy local inventory and Packer examples without replacing existing files.
secrets-init:
    @python3 scripts/local-secrets.py init

# Create .vaultpass using a hidden, confirmed prompt; preserve an existing file.
vaultpass:
    @python3 scripts/local-secrets.py vaultpass

# Encrypt local inventory secrets after editing placeholders; skip encrypted files.
secrets-encrypt:
    @python3 scripts/local-secrets.py encrypt

# Install control-node system packages and VMware SDKs (after secrets setup).
control-node *args:
    .venv/vmware/bin/ansible-playbook playbooks/00-control-node.yml "$@"

# Check site playbook syntax without contacting infrastructure.
syntax *args:
    .venv/vmware/bin/ansible-playbook playbooks/99-site-run.yml --syntax-check "$@"

# Display inventory, validate ESXi access, and check site syntax.
validate *args:
    .venv/vmware/bin/ansible-inventory --graph
    .venv/vmware/bin/ansible-playbook playbooks/00-validate.yml "$@"
    .venv/vmware/bin/ansible-playbook playbooks/99-site-run.yml --syntax-check "$@"

# Validate Packer inputs for esxi-6.7 or esxi-8 without creating VMs.
packer-validate target *args:
    ./packer/build-ubuntu-vms.sh --target "$@" --validate-only

# Create VMs for an explicit ESXi target; optionally pass VM files or --start-at.
packer-build target *args:
    ./packer/build-ubuntu-vms.sh --target "$@"
