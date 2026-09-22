#!/usr/bin/env bash
# Explicit system setup; run as the operator account, with sudo available.
set -euo pipefail

source /etc/os-release
if [[ "${ID:-}" != ubuntu ]]; then
  echo "Bootstrap supports Ubuntu 22.04 and 24.04 only." >&2
  exit 1
fi
case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *) echo "Bootstrap supports Ubuntu 22.04 and 24.04 only." >&2; exit 1 ;;
esac

sudo apt-get update
sudo apt-get install -y ca-certificates software-properties-common
if [[ "$VERSION_ID" == 22.04 ]]; then
  echo "Ubuntu 22.04: adding the third-party Deadsnakes PPA for Python 3.12."
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update
fi
sudo apt-get install -y python3.12 python3.12-venv
/usr/bin/python3.12 --version
echo "Python is ready. Run just deps to install project dependencies."
