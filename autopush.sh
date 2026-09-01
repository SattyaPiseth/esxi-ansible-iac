#!/usr/bin/env bash

set -euo pipefail

REMOTE="origin"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT_MSG=""
AUTO_PULL=false
RUN_VALIDATE=false
YES=false

usage() {
  cat <<'USAGE'
Usage: ./autopush.sh [options] [commit-message]

Options:
  -r, --remote <remote>       Remote to push (default: origin)
  -b, --branch <branch>       Branch to push (default: current branch)
  -p, --pull                  Pull before committing
  -v, --validate              Run Ansible syntax checks before push
  -y, --yes                   Skip confirmation prompt
  -h, --help                  Show this help

Examples:
  ./autopush.sh "Update docs"
  ./autopush.sh --validate "Harden guest bootstrap"
  ./autopush.sh --pull --validate --yes "Apply reviewed changes"
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--remote)
      REMOTE="${2:-}"
      [[ -n "$REMOTE" ]] || die "Missing value for $1"
      shift 2
      ;;
    -b|--branch)
      BRANCH="${2:-}"
      [[ -n "$BRANCH" ]] || die "Missing value for $1"
      shift 2
      ;;
    -p|--pull)
      AUTO_PULL=true
      shift
      ;;
    -v|--validate)
      RUN_VALIDATE=true
      shift
      ;;
    -y|--yes)
      YES=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="$1"
      else
        die "Unexpected argument: $1"
      fi
      shift
      ;;
  esac
done

[[ "$BRANCH" != "HEAD" ]] || die "Detached HEAD; checkout a branch first."

if [[ -z "$COMMIT_MSG" ]]; then
  COMMIT_MSG="Update IaC configuration"
fi

blocked_paths=(
  ".vaultpass"
  ".idea"
  ".generated"
  "packer/ubuntu-24.04/local.pkrvars.hcl"
)

for path in "${blocked_paths[@]}"; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    die "Blocked tracked local/secret path: $path"
  fi
done

if git ls-files '*.pkrvars.hcl' ':!:*.pkrvars.hcl.example' | grep -q .; then
  die "Blocked tracked real Packer variable file (*.pkrvars.hcl)."
fi

if git status --porcelain --ignored=no | grep -E '(^|[[:space:]])(\.vaultpass|\.idea/|\.generated/|packer/ubuntu-24\.04/local\.pkrvars\.hcl)$' >/dev/null; then
  die "Blocked local/secret path appears in git status."
fi

echo "Current branch: $BRANCH"
echo "Remote: $REMOTE"
echo
git status --short
echo

if ! $YES; then
  read -r -p "Commit and push these changes? Type 'yes' to continue: " answer
  [[ "$answer" == "yes" ]] || die "Aborted."
fi

if $AUTO_PULL; then
  git pull "$REMOTE" "$BRANCH"
fi

if $RUN_VALIDATE; then
  ansible-inventory --graph >/dev/null
  for playbook in playbooks/*.yml; do
    ansible-playbook "$playbook" --syntax-check
  done
fi

git add -A
git commit -m "$COMMIT_MSG" || {
  echo "Nothing to commit."
  exit 0
}
git push "$REMOTE" "$BRANCH"
