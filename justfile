# Compatible with Ubuntu 24.04's just 1.21.
set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments
export PATH := justfile_directory() + "/.venv/vmware/bin:" + env_var("PATH")

# Show available project commands.
default:
    @just --list

# Install system Python 3.12 using sudo; Ubuntu 22.04 adds the Deadsnakes PPA.
bootstrap:
    bash scripts/bootstrap-control-node.sh

# Install Packer, pinned Python tools, and Ansible collections.
deps $python="python3.12": packer-install
    @command -v "$python" >/dev/null || { echo "Install $python and its venv support first, or run just deps /path/to/python3.12." >&2; exit 1; }
    @"$python" -c 'import sys; sys.exit("Ansible dependencies require Python 3.12 or newer.") if sys.version_info < (3, 12) else None'
    @if [ -x .venv/vmware/bin/python ]; then .venv/vmware/bin/python -c 'import sys; sys.exit("Existing .venv/vmware uses Python <3.12. Move it to a backup path, then rerun just deps.") if sys.version_info < (3, 12) else None'; fi
    "$python" -m venv .venv/vmware
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

# Show inventory-defined allowed power states without changing VM power.
vm-power-states:
    .venv/vmware/bin/ansible managed_vm_esxi -m ansible.builtin.debug -a var=esxi_allowed_power_states

# Change one managed VM's power state: vm-power VM STATE [Ansible options].
vm-power $vm $state *args:
    @shift 2; .venv/vmware/bin/ansible-playbook playbooks/04-vm-power.yml "$@" --extra-vars "$(python3 -c 'import json, os; print(json.dumps({"scope": "single", "vm_power_name": os.environ["vm"], "vm_power_state": os.environ["state"]}))')"

# Change all managed VMs; optionally restrict the owning ESXi host with --limit.
vm-power-all $state *args:
    @shift; .venv/vmware/bin/ansible-playbook playbooks/04-vm-power.yml "$@" --extra-vars "$(python3 -c 'import json, os; print(json.dumps({"scope": "all", "vm_power_state": os.environ["state"]}))')"

# Delete one managed VM; repeat its exact name to confirm. Add --check to preview.
vm-delete $vm $confirm *args:
    @test -n "$vm" && test "$vm" = "$confirm" || { echo "Deletion blocked: repeat the exact VM name as confirmation." >&2; exit 1; }
    @shift 2; .venv/vmware/bin/ansible-playbook playbooks/05-vm-delete.yml "$@" --extra-vars "$(python3 -c 'import json, os; print(json.dumps({"scope": "single", "vm_delete_name": os.environ["vm"], "vm_delete_confirm": True, "vm_delete_confirm_name": os.environ["confirm"]}))')"
