#!/usr/bin/env bash

set -euo pipefail

PACKER_DIR="packer/ubuntu-24.04"
COMMON_VAR_FILE="$PACKER_DIR/local.pkrvars.hcl"
VM_VAR_DIR="$PACKER_DIR/vms/esxi-8"
FORCE=false
ON_ERROR=""
START_AT=""
VM_FILES=()

usage() {
  cat <<'USAGE'
Usage: packer/build-ubuntu-vms.sh [options] [vm-var-file ...]

Build Ubuntu VMs with one optional common local var file and one VM var file per VM.

Options:
  -f, --force             Pass --force to packer build
  --common-var-file FILE  Use a common ESXi/credential var file instead of local.pkrvars.hcl
  --vm-var-dir DIR        Discover VM var files from this directory
  --on-error <action>     Pass -on-error=<action> to packer build, e.g. ask
  --start-at FILE         Continue from this VM var file after a partial run
  -h, --help              Show this help

Examples:
  packer/build-ubuntu-vms.sh
  packer/build-ubuntu-vms.sh --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl
  packer/build-ubuntu-vms.sh --vm-var-dir packer/ubuntu-24.04/vms/esxi-8
  packer/build-ubuntu-vms.sh --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
  packer/build-ubuntu-vms.sh --force packer/ubuntu-24.04/vms/esxi-8/mgmt-01.pkrvars.hcl
  packer/build-ubuntu-vms.sh --force --on-error ask
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--force)
      FORCE=true
      shift
      ;;
    --on-error)
      ON_ERROR="${2:-}"
      [[ -n "$ON_ERROR" ]] || die "Missing value for --on-error"
      shift 2
      ;;
    --common-var-file)
      COMMON_VAR_FILE="${2:-}"
      [[ -n "$COMMON_VAR_FILE" ]] || die "Missing value for --common-var-file"
      [[ -f "$COMMON_VAR_FILE" ]] || die "Missing common var file: $COMMON_VAR_FILE"
      shift 2
      ;;
    --vm-var-dir)
      VM_VAR_DIR="${2:-}"
      [[ -n "$VM_VAR_DIR" ]] || die "Missing value for --vm-var-dir"
      [[ -d "$VM_VAR_DIR" ]] || die "Missing VM var directory: $VM_VAR_DIR"
      shift 2
      ;;
    --start-at)
      START_AT="${2:-}"
      [[ -n "$START_AT" ]] || die "Missing value for --start-at"
      [[ -f "$START_AT" ]] || die "Missing start-at VM var file: $START_AT"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      VM_FILES+=("$1")
      shift
      ;;
  esac
done

if [[ -f "$COMMON_VAR_FILE" ]]; then
  COMMON_VAR_ARGS=(-var-file="$COMMON_VAR_FILE")
else
  COMMON_VAR_ARGS=()
fi

if [[ ${#VM_FILES[@]} -eq 0 ]]; then
  mapfile -t VM_FILES < <(find "$VM_VAR_DIR" -maxdepth 1 -type f -name '*.pkrvars.hcl' | sort)
fi

[[ ${#VM_FILES[@]} -gt 0 ]] || die "No VM var files found. Copy examples from $VM_VAR_DIR/*.example to *.pkrvars.hcl first."

if [[ -n "$START_AT" ]]; then
  RESUME_FILES=()
  START_FOUND=false
  for vm_file in "${VM_FILES[@]}"; do
    if [[ "$vm_file" == "$START_AT" ]]; then
      START_FOUND=true
    fi
    if [[ "$START_FOUND" == "true" ]]; then
      RESUME_FILES+=("$vm_file")
    fi
  done
  if [[ "$START_FOUND" != "true" ]]; then
    die "Start-at file is not in the selected VM file list: $START_AT"
  fi
  VM_FILES=("${RESUME_FILES[@]}")
fi

packer init "$PACKER_DIR"
packer fmt "$PACKER_DIR"

for vm_file in "${VM_FILES[@]}"; do
  [[ -f "$vm_file" ]] || die "Missing VM var file: $vm_file"

  echo "Validating $vm_file"
  packer validate \
    "${COMMON_VAR_ARGS[@]}" \
    -var-file="$vm_file" \
    "$PACKER_DIR"

  cmd=(packer build)
  if [[ "$FORCE" == "true" ]]; then
    cmd+=(--force)
  fi
  [[ -z "$ON_ERROR" ]] || cmd+=("-on-error=$ON_ERROR")
  cmd+=( "${COMMON_VAR_ARGS[@]}" -var-file="$vm_file" "$PACKER_DIR" )

  echo "Building $vm_file"
  "${cmd[@]}"
done
