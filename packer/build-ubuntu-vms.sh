#!/usr/bin/env bash

set -euo pipefail

PACKER_DIR="packer/ubuntu-24.04"
TARGET=""
VALIDATE_ONLY=false
FORCE=false
ON_ERROR=""
START_AT=""
VM_FILES=()

usage() {
  cat <<'USAGE'
Usage: packer/build-ubuntu-vms.sh --target <esxi-6.7|esxi-8> [options] [vm-var-file ...]

Validate or build Ubuntu VMs for one explicitly selected ESXi target. The target
selects both the common variable file and the directory containing VM variables.

Options:
  --target TARGET     Required ESXi target: esxi-6.7 or esxi-8
  --validate-only     Initialize, format-check, and validate; do not build VMs
  -f, --force         Pass --force to packer build
  --on-error ACTION   Pass -on-error=ACTION to packer build, for example ask
  --start-at FILE     Continue from this VM variable file after a partial run
  -h, --help          Show this help

Examples:
  packer/build-ubuntu-vms.sh --target esxi-6.7 --validate-only
  packer/build-ubuntu-vms.sh --target esxi-8
  packer/build-ubuntu-vms.sh --target esxi-8 packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
  packer/build-ubuntu-vms.sh --target esxi-8 --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-02.pkrvars.hcl
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      [[ -n "$TARGET" ]] || die "Missing value for --target"
      shift 2
      ;;
    --validate-only)
      VALIDATE_ONLY=true
      shift
      ;;
    -f|--force)
      FORCE=true
      shift
      ;;
    --on-error)
      ON_ERROR="${2:-}"
      [[ -n "$ON_ERROR" ]] || die "Missing value for --on-error"
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
    --*)
      die "Unknown option: $1"
      ;;
    *)
      VM_FILES+=("$1")
      shift
      ;;
  esac
done

case "$TARGET" in
  esxi-6.7|esxi-8) ;;
  "") die "Pass an explicit target with --target esxi-6.7 or --target esxi-8" ;;
  *) die "Unsupported target '$TARGET'; expected esxi-6.7 or esxi-8" ;;
esac

command -v packer >/dev/null 2>&1 || die "Packer 1.16.1 is required but was not found in PATH. Install it from https://developer.hashicorp.com/packer/install"

COMMON_VAR_FILE="$PACKER_DIR/$TARGET.pkrvars.hcl"
VM_VAR_DIR="$PACKER_DIR/vms/$TARGET"

[[ -f "$COMMON_VAR_FILE" ]] || die "Missing common var file: $COMMON_VAR_FILE (copy its .example file first)"
[[ -d "$VM_VAR_DIR" ]] || die "Missing VM var directory: $VM_VAR_DIR"

if [[ ${#VM_FILES[@]} -eq 0 ]]; then
  mapfile -t VM_FILES < <(find "$VM_VAR_DIR" -maxdepth 1 -type f -name '*.pkrvars.hcl' | sort)
fi

[[ ${#VM_FILES[@]} -gt 0 ]] || die "No VM var files found. Copy examples in $VM_VAR_DIR to *.pkrvars.hcl first."

for vm_file in "${VM_FILES[@]}"; do
  [[ -f "$vm_file" ]] || die "Missing VM var file: $vm_file"
  case "$vm_file" in
    "$VM_VAR_DIR"/*) ;;
    *) die "VM var file '$vm_file' does not belong to target '$TARGET' ($VM_VAR_DIR)" ;;
  esac
done

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
  [[ "$START_FOUND" == "true" ]] || die "Start-at file is not in the selected VM file list: $START_AT"
  VM_FILES=("${RESUME_FILES[@]}")
fi

echo "Target: $TARGET"
echo "Common variables: $COMMON_VAR_FILE"
printf 'VM variables: %s\n' "${VM_FILES[@]}"

packer init "$PACKER_DIR"
packer fmt -check -recursive "$PACKER_DIR"

for vm_file in "${VM_FILES[@]}"; do
  echo "Validating $vm_file"
  packer validate \
    -var-file="$COMMON_VAR_FILE" \
    -var-file="$vm_file" \
    "$PACKER_DIR"

  if [[ "$VALIDATE_ONLY" == "true" ]]; then
    continue
  fi

  cmd=(packer build)
  if [[ "$FORCE" == "true" ]]; then
    cmd+=(--force)
  fi
  [[ -z "$ON_ERROR" ]] || cmd+=("-on-error=$ON_ERROR")
  cmd+=(-var-file="$COMMON_VAR_FILE" -var-file="$vm_file" "$PACKER_DIR")

  echo "Building $vm_file"
  "${cmd[@]}"
done
