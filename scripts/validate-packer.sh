#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKER_DIR="$REPOSITORY_ROOT/packer/ubuntu-24.04"

command -v packer >/dev/null 2>&1 || {
  echo "ERROR: packer is required but was not found in PATH." >&2
  exit 1
}

packer init "$PACKER_DIR"
packer fmt -check -recursive "$PACKER_DIR"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

for target in esxi-6.7 esxi-8; do
  common_example="$PACKER_DIR/$target.pkrvars.hcl.example"
  vm_var_dir="$PACKER_DIR/vms/$target"

  [[ -f "$common_example" ]] || {
    echo "ERROR: missing common variable example: $common_example" >&2
    exit 1
  }

  common_vars="$TEMP_DIR/$target.pkrvars.hcl"
  cp "$common_example" "$common_vars"

  mapfile -t vm_vars < <(find "$vm_var_dir" -maxdepth 1 -type f -name '*.pkrvars.hcl.example' | sort)
  [[ ${#vm_vars[@]} -gt 0 ]] || {
    echo "ERROR: no VM variable examples found in $vm_var_dir" >&2
    exit 1
  }

  for vm_vars_file in "${vm_vars[@]}"; do
    staged_vm_vars="$TEMP_DIR/$target-$(basename "${vm_vars_file%.example}")"
    cp "$vm_vars_file" "$staged_vm_vars"
    echo "Validating $target with $(basename "$vm_vars_file")"
    packer fmt -check "$common_vars" "$staged_vm_vars"
    packer validate \
      -var-file="$common_vars" \
      -var-file="$staged_vm_vars" \
      "$PACKER_DIR"
  done
done
