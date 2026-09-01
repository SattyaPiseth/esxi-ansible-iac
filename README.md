# ESXi Ansible IaC

Production-oriented Infrastructure as Code for a standalone VMware ESXi host.

The current supported workflow is:

```text
Packer Ubuntu autoinstall build -> Ansible power -> SSH wait -> guest bootstrap
```

Packer owns VM creation and OS installation. Ansible owns ESXi runtime actions,
SSH readiness, guest bootstrap, and safe deletion.

## What This Manages

- ESXi connection validation and host fact gathering.
- VM power operations on standalone ESXi.
- SSH host-key refresh and SSH readiness checks.
- Linux guest package and service bootstrap.
- Safe VM deletion with explicit confirmation.
- Ubuntu 24.04 VM builds through Packer and Ubuntu autoinstall.

## Repository Layout

```text
ansible.cfg                         Ansible defaults
requirements.yml                    Pinned Ansible collections
inventories/production/             Production inventory and variables
playbooks/                          Entry-point playbooks
packer/ubuntu-24.04/                Packer Ubuntu autoinstall build
roles/                              Reusable ESXi and guest roles
```

## Prerequisites

Run Ansible from a Linux control node or container with:

- Ansible
- Pinned collections from `requirements.yml`
- VMware Python dependencies required by the VMware collections
- Network access to ESXi and guest VMs

Install collections:

```bash
ansible-galaxy collection install -r requirements.yml
```

Install control-node dependencies used by Ansible's VMware modules:

```bash
ansible-playbook playbooks/00-control-node.yml
.venv/vmware/bin/python -c "import pyVim, pyVmomi; print('pyvmomi ok')"
```

Packer is required only for building/rebuilding Ubuntu VMs:

```bash
packer init packer/ubuntu-24.04
```

### Control Node And Project Copy

The repository does not install or upgrade the operating system of the machine
where it is copied. Packer creates the managed Ubuntu 24.04 VMs; Ansible then
configures them remotely. Kubernetes control-plane and worker nodes do not need
their own copy of this repository.

Keep one authoritative clone on the Ansible control node. For the current
Kubespray release, Ubuntu 24.04 is the simplest control-node choice because its
Python version satisfies the pinned Kubespray requirements. Prefer a normal Git
clone and subsequent `git pull` operations when the control node can reach the
repository:

```bash
git clone <repository-url> /home/sysadmin/esxi-ansible-iac
cd /home/sysadmin/esxi-ansible-iac
git pull
```

When Git access is unavailable, push a working-tree snapshot to one inventory
host with the safe synchronization playbook. Run `99-guest-site.yml` first so the
destination has `rsync`, which `ansible.posix.synchronize` requires on both
ends:

```bash
ansible-playbook playbooks/18-project-sync.yml \
  -e target_host=ubuntu_24.04-mgmt-01
```

Do not use `scp -r` for the project. It also copies `.git`, virtual
environments, generated artifacts, and local configuration that does not belong
on a managed VM. The synchronization playbook excludes those paths and does not
preserve source owner/group metadata. It intentionally does not copy
`~/.ssh/esxi_ansible_ed25519` or `.vaultpass`; provision those credentials
separately on a control node and keep their permissions restricted.

## Inventory

Default inventory:

```text
inventories/production/hosts.yml
```

Groups:

- `vmware_esxi` - standalone ESXi API target.
- `managed_vms` - Linux guests managed after Packer has built them.
- `discovered_managed_vms` - temporary in-memory guests discovered from ESXi.

Common Linux SSH and become settings live in
`inventories/production/group_vars/managed_vms/main.yml`. The discovered-guest
playbooks copy credentials from `guest_credential_source`, which defaults to
`ubuntu_24.04-mgmt-01`.

Check inventory:

```bash
ansible-inventory --graph
ansible-inventory --host vm_esxi_8.0
ansible-inventory --host vm_esxi_6.7
ansible-inventory --host ubuntu_24.04-mgmt-01
```

The `vmware_esxi` group can contain multiple standalone ESXi API targets.
Shared defaults such as username, datacenter, folder, and certificate policy
live in `inventories/production/group_vars/vmware_esxi.yml`. Host-specific
values such as `esxi_hostname` and the VM placement list live in
`inventories/production/host_vars/<esxi_inventory_name>/main.yml`.

## Secrets

The repo expects an ignored local vault password file:

```text
.vaultpass
```

Do not commit `.vaultpass` or real `*.pkrvars.hcl` files.

Edit vaulted variables:

```bash
ansible-vault edit inventories/production/host_vars/vm_esxi_8.0/vault.yml
ansible-vault create inventories/production/host_vars/vm_esxi_6.7/vault.yml
ansible-vault edit inventories/production/host_vars/localhost/vault.yml
ansible-vault edit inventories/production/group_vars/managed_vms/vault.yml
```

Required vaulted values:

```yaml
# inventories/production/host_vars/vm_esxi_8.0/vault.yml
esxi_password: "ROTATED_ESXI_PASSWORD"
```

```yaml
# inventories/production/host_vars/vm_esxi_6.7/vault.yml
esxi_password: "ROTATED_ESXI_6_7_PASSWORD"
```

```yaml
# inventories/production/host_vars/localhost/vault.yml
ansible_become_password: "ROTATED_CONTROL_NODE_SUDO_PASSWORD"
```

```yaml
# inventories/production/group_vars/managed_vms/vault.yml
ansible_password: "ROTATED_GUEST_PASSWORD"
ansible_become_password: "{{ ansible_password }}"
```

Use `host_vars/localhost/vault.yml` only for sudo on the Ansible/Kubespray
control node. Use `group_vars/managed_vms/vault.yml` for SSH and sudo on the
Kubernetes nodes. Keeping these separate avoids reusing the control-node sudo
secret as a remote node secret. The Kubespray control role sets `become: true`
only on tasks that need local privilege escalation.

Use a group vault for `managed_vms` when all Packer-built Ubuntu guests share the
same bootstrap account password. Keeping `ansible_password` only under one
host, such as `host_vars/ubuntu_24.04-mgmt-01/vault.yml`, leaves the other
inventory guests without SSH and sudo credentials.

Kubespray also needs sudo access on the Kubernetes nodes. The generated
Kubespray inventory reads the become password from the
`KUBESPRAY_BECOME_PASSWORD` environment variable instead of writing the secret
to `.generated/`. When you deploy through `playbooks/99-kubernetes-site.yml`, the
wrapper passes the decrypted `ansible_become_password` from Ansible Vault into
that environment variable automatically.

## Packer Ubuntu Build

Create a local var file from the ESXi 8 example if you want one default build
target:

```bash
cp packer/ubuntu-24.04/esxi-8.pkrvars.hcl.example packer/ubuntu-24.04/local.pkrvars.hcl
```

For multiple ESXi targets, keep one ignored common var file per host:

```bash
cp packer/ubuntu-24.04/esxi-8.pkrvars.hcl.example packer/ubuntu-24.04/esxi-8.pkrvars.hcl
cp packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl.example packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl
```

Fill in ESXi credentials and any guest bootstrap secret values that you do not
want to source from `PKR_VAR_*` environment variables. Then validate one target:

```bash
packer fmt packer/ubuntu-24.04
packer validate -var-file=packer/ubuntu-24.04/esxi-8.pkrvars.hcl packer/ubuntu-24.04
```

If you prefer environment-only secrets, skip local ESXi var files and set
`PKR_VAR_esxi_password`, `PKR_VAR_ssh_password`, and
`PKR_VAR_ssh_password_hash` before running `packer validate` or `packer build`.

For test builds, override the VM name to avoid replacing the production VM:

```bash
packer build \
  -var-file=packer/ubuntu-24.04/local.pkrvars.hcl \
  -var vm_name=ubuntu_24.04-test-01 \
  packer/ubuntu-24.04
```

The Packer template uses Ubuntu autoinstall via NoCloud HTTP. The guest base
role installs the common operational tools used by this project, including
`open-vm-tools`, `curl`, `git`, `iproute2`, `dnsutils`, `iputils-ping`, and
`openssh-client`, enables `open-vm-tools`, then shuts down the VM after the
build. Optional operator packages are set in inventory, not in the role
defaults. The production inventory installs `fish`, `tree`, and Ubuntu's
Python/jq-wrapper implementation of `yq` through APT. It installs the official
Python `tldr` client from the Snap Store's stable channel, then removes the
transitional `tldr` package and its underlying `tldr-hs` APT implementation.
It also installs `fastfetch` from the `zhangsongcui3371/fastfetch` Launchpad
PPA via `guest_base_operator_repositories` using deb822 repository entries. Use
a separately pinned package source if automation requires Mike Farah's Go `yq`,
whose command syntax differs from Ubuntu's `yq` package.

Packer input values come from the template defaults in
`packer/ubuntu-24.04/ubuntu-24.04.pkr.hcl`, the ignored
`packer/ubuntu-24.04/*.pkrvars.hcl`, or `PKR_VAR_*` environment variables.
Keep common ESXi var files small: use them for ESXi credentials and any values
that must differ from the defaults. Marking a variable `sensitive = true` only
hides it from Packer output; it does not turn the var file into secret storage.

The batch helper `packer/build-ubuntu-vms.sh` uses
`packer/ubuntu-24.04/local.pkrvars.hcl` when it exists. Use
`--common-var-file` to target a specific ESXi host:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-8 \
  --force --on-error ask
```

If you prefer, set secrets only through `PKR_VAR_*` and let the helper use the
template defaults plus the per-VM var files.

The helper validates and builds each VM var file as a separate Packer run. If a
multi-VM build stops part way through, continue from the failed VM instead of
rebuilding earlier VMs:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-8 \
  --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl \
  --force --on-error ask
```

Use `--on-error ask` while troubleshooting installer or SSH timing problems.
Use `--force` only when replacing an existing VM artifact is intentional.

If a guest already has a stale `ppa:ansible/ansible` source from an earlier
test run, remove that source once before rerunning the guest bootstrap. The
guest role does not manage the Ansible package on managed VMs.

Current lab builds allow insecure ESXi TLS because the standalone ESXi host is
using an untrusted/old VMCA certificate. Set `esxi_insecure_connection=false`
after replacing the ESXi certificate or installing the matching CA in the
control environment.

`vm_name` is the vSphere VM object name. `guest_hostname` is the hostname written
inside Ubuntu. Keep `guest_hostname` DNS-safe with letters, numbers, and hyphens
only, for example `ubuntu-24-04-mgmt-01`. Names such as
`ubuntu_24.04-mgmt-01` are acceptable in vSphere but are not valid Linux
hostnames.

For multiple VMs, keep ESXi and guest credential settings in an ignored common
var file, and keep VM-specific var files under an ESXi-specific directory:

```text
packer/ubuntu-24.04/vms/esxi-8/
packer/ubuntu-24.04/vms/esxi-6.7/
```

Build ESXi 6.7 only with VM var files intended for that host.
The ESXi 6.7 common example keeps EFI firmware and uses a slower
`boot_keygroup_interval` because older standalone ESXi consoles can reject or
drop keyboard scan codes during Packer boot-command injection. Do not use BIOS
for this host unless you first confirm the Ubuntu ISO boots from CD-ROM in BIOS
mode; in this environment BIOS fell through to PXE with `Operating System not
found`, so EFI is the supported setting.

For this ESXi 6.7 host, the Ubuntu ISO path is case-sensitive and should resolve
to:

```text
[RAID1-OS] ISO/ubuntu-24.04.4-live-server-amd64.iso
```

If Packer reports `vim.fault.InvalidState` while typing the boot command, power
off and delete the failed VM, then retry with `boot_wait` around `35s` to `36s`.
If the VM reaches the Ubuntu language selector, `boot_wait` is too high because
Packer missed the GRUB edit window; lower it toward `33s`. Keep watching the VM
console while tuning: Packer must type while the GRUB menu is visible.

Create real local VM var files from the tracked examples:

```bash
cp packer/ubuntu-24.04/vms/esxi-8/mgmt-01.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/mgmt-01.pkrvars.hcl
cp packer/ubuntu-24.04/vms/esxi-8/mgmt-02.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/mgmt-02.pkrvars.hcl
cp packer/ubuntu-24.04/vms/esxi-8/mgmt-03.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/mgmt-03.pkrvars.hcl
cp packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
cp packer/ubuntu-24.04/vms/esxi-8/wrk-02.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/wrk-02.pkrvars.hcl
cp packer/ubuntu-24.04/vms/esxi-8/wrk-03.pkrvars.hcl.example packer/ubuntu-24.04/vms/esxi-8/wrk-03.pkrvars.hcl
```

Build one VM:

```bash
packer build \
  -var-file=packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  -var-file=packer/ubuntu-24.04/vms/esxi-8/mgmt-01.pkrvars.hcl \
  packer/ubuntu-24.04
```

Build all local VM var files against the default `local.pkrvars.hcl`:

```bash
packer/build-ubuntu-vms.sh --force --on-error ask
```

Build all local VM var files against a specific ESXi host:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-8 \
  --force --on-error ask
```

Build all local VM var files for ESXi 6.7:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-6.7 \
  --force --on-error ask
```

Continue after a failed VM build:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-8 \
  --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl \
  --force --on-error ask
```

The default `boot_wait` and `ssh_timeout` values are deliberately conservative
for standalone ESXi and Ubuntu ISO boot timing:

```hcl
boot_wait = "15s"
boot_keygroup_interval = "100ms"
vm_firmware = "efi"
ssh_timeout = "75m"
```

For debugging intermittent installer or SSH timeouts, preserve the failed VM:

```bash
packer build -on-error=ask -var-file=packer/ubuntu-24.04/local.pkrvars.hcl packer/ubuntu-24.04
```

## Ansible Validation

```bash
ansible-playbook playbooks/99-site-run.yml --syntax-check
ansible-playbook playbooks/00-validate.yml
ansible-playbook playbooks/01-esxi-facts.yml
ansible-playbook playbooks/02-vm-list.yml
ansible-playbook playbooks/03-vm-validate-managed.yml
```

## Runtime Workflow

Read-only ESXi validation and inventory playbooks run against every host in the
`vmware_esxi` group. Use `--limit vm_esxi_8.0` or `--limit vm_esxi_6.7` when
checking one ESXi host. VM lifecycle and Kubernetes inventory playbooks remain
scoped to `vm_esxi_8.0` until VM placement is intentionally moved to another
host.

Power on a Packer-built VM:

```bash
ansible-playbook playbooks/04-vm-power.yml \
  -e vm_power_name=ubuntu_24.04-mgmt-01 \
  -e vm_power_state=powered-on
```

Power on all VMs in the `managed_vms` inventory group:

```bash
ansible-playbook playbooks/04-vm-power.yml -e scope=all -e vm_power_state=powered-on
```

Power off all managed VMs:

```bash
ansible-playbook playbooks/04-vm-power.yml -e scope=all -e vm_power_state=powered-off
```

Power only selected VMs by overriding `vm_power_targets`:

```bash
ansible-playbook playbooks/04-vm-power.yml \
  -e scope=all \
  -e vm_power_state=powered-on \
  -e '{"vm_power_targets":["ubuntu_24.04-mgmt-01","ubuntu_24.04-wrk-01"]}'
```

Bootstrap guests in inventory:

```bash
ansible-playbook playbooks/99-guest-site.yml
```

Managed guests use their inventory `ansible_host` as a static `/24` address.
Shared Netplan values are defined once under `managed_vms`:

```yaml
guest_network_gateway: 172.16.6.1
guest_network_nameservers:
  - 172.16.1.2
guest_network_search_domains:
  - "tss.local"
guest_network_dns_test_name: >-
  dns.tss.local
```

`tss.local` is the internal search domain for this lab. The DNS validation
target is `dns.tss.local`, which confirms the internal resolver path is working
without depending on the ESXi hostname record being present. `/etc/resolv.conf`
should continue to point at the local `127.0.0.53` systemd-resolved stub; do
not replace it with a static file.

The internal resolver must forward public queries to its upstream resolvers.
Do not add public resolvers directly beside `172.16.1.2`: they do not serve
`tss.local` and systemd-resolved does not treat them as ordered fallbacks for
the private zone.

Reserve or exclude every managed `172.16.6.x` address from the DHCP pool before
applying static networking. Netplan cannot prevent the DHCP server from leasing
the same address to another device.

The role backs up installer/cloud-init Netplan YAML files under
`/etc/netplan/.ansible-backup`, disables cloud-init network regeneration, and
manages one authoritative `/etc/netplan/99-ansible-static.yaml` file. Each run
validates the generated configuration, applies it one guest at a time, waits
for SSH to reconnect, flushes the local resolver cache, and then verifies the
effective route and DNS state. Do not run `netplan try` through Ansible because
it requires interactive confirmation; the role uses the non-interactive
`netplan apply` command after `netplan generate` succeeds.

To apply only guest networking after connectivity is already verified:

```bash
ansible-playbook playbooks/11-guest-network.yml
```

The `managed_vms` inventory selects `~/.ssh/esxi_ansible_ed25519` with
`IdentitiesOnly=yes` and manages its matching `.pub` file on every guest. Guest
playbooks therefore do not depend on `ssh-agent` or repeated key extra-vars.

If the run appears stuck at `vm_wait : Wait for guest connection`, test SSH auth
directly against one guest:

```bash
ansible ubuntu_24.04-mgmt-02 -m ping -vvv
ansible ubuntu_24.04-mgmt-02 -m command -a whoami -b -vvv
```

`known_hosts` only verifies that TCP/22 is reachable. `vm_wait` is the first
step that authenticates over SSH, so failures there usually mean the guest
password, SSH key, or sudo/become password is not configured for that host.

After SSH keys are installed and verified, disable password SSH:

```bash
ansible-playbook playbooks/99-guest-site.yml -e guest_base_enable_password_ssh_disabled=true
```

Best-practice SSH key workflow for all Linux VMs:

```bash
key="$HOME/.ssh/esxi_ansible_ed25519"

if [ ! -f "$key" ]; then
  ssh-keygen -t ed25519 -a 100 -N "" -f "$key" -C ansible@esxi-iac
fi

if [ ! -f "$key.pub" ]; then
  ssh-keygen -y -f "$key" > "$key.pub"
  chmod 0644 "$key.pub"
fi

ansible-playbook playbooks/99-guest-site.yml

ansible managed_vms -m ping

ansible managed_vms -m command -a whoami -b
```

Never overwrite this private key after deploying its public key. If the public
key is missing or mismatched, reconstruct only the `.pub` file with
`ssh-keygen -y -f "$key" > "$key.pub"`.

### SSH Key Rotation

Rotate the shared key by adding and validating a replacement before removing
the current key. Confirm all guests are reachable with the canonical key and
Vault provides `ansible_become_password` for `sysadmin`. Do not run
`99-guest-site.yml` during an active rotation.

Generate the replacement under the `_next` path; never overwrite the canonical
keypair:

```bash
key="$HOME/.ssh/esxi_ansible_ed25519"
next_key="${key}_next"
test ! -e "$next_key" && test ! -e "$next_key.pub"
ssh-keygen -t ed25519 -a 100 -N "" -f "$next_key" -C ansible@esxi-iac
```

Deploy the replacement alongside the current key and validate fresh SSH access
with it:

```bash
ansible-playbook playbooks/17-ssh-key-rotate.yml -e rotation_phase=deploy
```

Do not continue unless every host passes `Verify rotated SSH key connectivity`.
Then connect with the replacement key, remove only the canonical public key,
and verify replacement-key access again:

```bash
ansible-playbook playbooks/17-ssh-key-rotate.yml -e rotation_phase=revoke
```

Promote the replacement and retain the retired pair under a unique name so a
later rotation cannot overwrite it:

```bash
backup="${key}_retired_$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$backup" && test ! -e "$backup.pub"
mv "$key" "$backup"
mv "$key.pub" "$backup.pub"
mv "$next_key" "$key"
mv "$next_key.pub" "$key.pub"
chmod 0600 "$key" "$backup"
chmod 0644 "$key.pub" "$backup.pub"

ssh-keygen -lf "$key" -E sha256
ssh-keygen -lf "$key.pub" -E sha256
ansible managed_vms -m ping
```

Retain the retired keypair until rotation is verified and backed up, then
delete it according to the credential-retention policy.

If the private key was accidentally replaced after password SSH was disabled,
recover only the affected guests through VMware Tools:

```bash
ansible-playbook playbooks/12-guest-ssh-recover.yml \
  -e guest_ssh_recovery_enable_recovery=true \
  -e '{"guest_ssh_recovery_vm_names":["ubuntu_24.04-mgmt-01","ubuntu_24.04-mgmt-03","ubuntu_24.04-wrk-01"]}'

ansible managed_vms -m ping
```

This recovery path requires VMware Tools, valid vaulted guest passwords, and an
ESXi license that permits API write operations. It is intentionally separate
from the normal site playbooks and is the only emergency exception to normal
`ansible.posix.authorized_key` management because a locked guest cannot be
reached through the SSH transport.

After key login and sudo are verified, disable password SSH:

```bash
ansible-playbook playbooks/99-guest-site.yml \
  -e guest_base_enable_password_ssh_disabled=true
```

The inventory validates that the `.pub` file matches the configured private
key before managing guests. Additional public keys can be defined in
`inventories/production/group_vars/managed_vms/ssh_keys.yml`; private keys remain
outside the repository. Normal guest bootstrap adds these keys without removing
existing access. Use the SSH key rotation procedure above for targeted key
replacement. For new Packer builds, you can also set `ssh_authorized_key` in the
ignored local Packer var file so the key is available from first boot.

Bootstrap a temporary test VM by overriding its IP:

```bash
ansible-playbook playbooks/99-guest-site.yml \
  -e ansible_host=172.16.6.16 \
  -e vm_power_name=ubuntu_24.04-test-01
```

For DHCP-based rebuilt test VMs, prefer discovering the current IP from ESXi:

```bash
ansible-playbook playbooks/99-guest-discover.yml \
  -e vm_power_name=ubuntu_24.04-test-01 \
  -e vm_power_state=powered-on \
  -e ssh_known_hosts_enable_remove_old=true
```

Bootstrap all managed DHCP-based VMs in the `managed_vms` inventory group:

```bash
ansible-playbook playbooks/99-guest-discover.yml \
  -e scope=all \
  -e vm_power_state=powered-on \
  -e ssh_known_hosts_enable_remove_old=true
```

On repeat runs, omit `ssh_known_hosts_enable_remove_old=true` unless VMs were rebuilt
and their SSH host keys changed.

## Kubespray Kubernetes Deployment

Kubespray uses its own inventory groups:

- `kube_control_plane` - Kubernetes API server, scheduler, and controller nodes.
- `etcd` - etcd members. Keep at least three members for failover.
- `kube_node` - schedulable worker nodes.

This repository derives vSphere VM object names from the `managed_vms` group, for
example `ubuntu_24.04-mgmt-01`, and renders DNS-safe Kubespray node names such
as `ubuntu-24-04-mgmt-01`. Keep the VM object name stable for ESXi/Packer and
the rendered node name stable for Kubernetes. The rendered node name is derived
by replacing `_` and `.` with `-`; use `kubespray_inventory_node_names` only if a host
needs an explicit override.

Default production layout:

```text
kube_control_plane / etcd:
  ubuntu_24.04-mgmt-01 -> ubuntu-24-04-mgmt-01
  ubuntu_24.04-mgmt-02 -> ubuntu-24-04-mgmt-02
  ubuntu_24.04-mgmt-03 -> ubuntu-24-04-mgmt-03

kube_node:
  ubuntu_24.04-wrk-01  -> ubuntu-24-04-wrk-01
  ubuntu_24.04-wrk-02  -> ubuntu-24-04-wrk-02
  ubuntu_24.04-wrk-03  -> ubuntu-24-04-wrk-03
```

Render the Kubespray inventory from the existing Ansible inventory:

```bash
ansible-playbook playbooks/07-kubespray-inventory.yml
```

The generated inventory is written under:

```text
.generated/kubespray/production/
```

Install Kubespray natively on the Ansible control node:

```bash
ansible-playbook playbooks/08-kubespray-install.yml -K
```

If the control-node user requires a sudo password, prompt for it:

```bash
ansible-playbook playbooks/08-kubespray-install.yml --ask-become-pass
```

This clones the pinned Kubespray release into `/opt/kubespray`, creates a
Python virtual environment, and installs Kubespray's Python requirements from
its `requirements.txt`.

Kubespray `v2.31.0` currently pins `ansible==11.13.0`. The control-node role
auto-selects the first compatible Python runtime from:

```yaml
kubespray_control_python_candidates:
  - python3.13
  - python3.12
  - python3.11
  - python3
```

If installation fails with an error like `No matching distribution found for
ansible==11.13.0`, the control-node Python runtime is not compatible with
Kubespray's required Ansible package. The Ansible control node must have Python
3.11-3.13 available. Verify and recreate the Kubespray venv:

```bash
python3 --version
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip
sudo rm -rf /opt/kubespray/.venv
ansible-playbook playbooks/08-kubespray-install.yml
```

If `python3 --version` is still lower than 3.11, install a compatible Python on
the manager or move the Ansible/Kubespray control node to Ubuntu 24.04.

Deploy the Kubernetes cluster:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true
```

Kubespray deploy output is hidden by default because the task passes the node
sudo password through an environment variable. To troubleshoot a failed
Kubespray run, temporarily reveal the output. The deployment role accepts the
control-node sudo password from Ansible Vault or from `-K` / `--ask-become-pass`:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e kubespray_control_enable_deploy_output_hidden=false -K
```

The wrapper sets `ANSIBLE_LOG_PATH` for the nested Kubespray process, writing a
log under the generated inventory directory. In another terminal, monitor
progress with:

```bash
tail -f .generated/kubespray/production/kubespray-deploy.log
```

The deployment preflight repairs ownership only under the generated
`artifacts` directory and removes stale artifacts before a new deployment.
This handles files left by an earlier root-run while keeping the downloaded
`admin.conf` restricted to mode `0600`. The nested Kubespray run defaults to a
small fork count to reduce control-node pressure. Run Kubespray as the normal
automation operator, not with `sudo ansible-playbook`.

If a partial deployment joined nodes before Calico completed, recover the CNI
through the same wrapper and Vault credentials:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e '{"kubespray_control_cluster_playbook_tags":["node","kubeadm","network"]}'
```

The `node` and `kubeadm` phases restore worker kernel modules, local API proxy,
kubelet, and kube-proxy prerequisites before Calico writes
`/etc/cni/net.d/calico-kubeconfig`. After all nodes report `Ready`, run the
deployment command again without `kubespray_control_cluster_playbook_tags` to complete
the remaining roles.

### Reset and Fresh Deploy After Node IP Changes

If control-plane or etcd node IPs change after deployment, rebuild the cluster
with Kubespray instead of editing or deleting `/etc/kubernetes` by hand. The old
IP addresses are stored in kubeconfigs, kube-apiserver static pod manifests,
kubelet configuration, etcd endpoints, and CNI state. A reset is destructive, so
only use this path when rebuilding is acceptable and etcd or workload state has
been backed up.

Kubespray reset uses the generated inventory, where `ansible_become` is enabled
for all nodes. Use the repository wrapper so the sudo password comes from
Ansible Vault or `--ask-become-pass` and is passed to Kubespray through
`KUBESPRAY_BECOME_PASSWORD` automatically:

```bash
cd ~/esxi-ansible-iac
ansible-playbook playbooks/15-kubespray-reset.yml \
  -e kubespray_control_enable_cluster_reset=true \
  -e kubespray_control_enable_deploy_output_hidden=false -K
```

The explicit `kubespray_control_enable_cluster_reset=true` flag prevents accidental destructive
resets. If sudo is provided from Vault, omit `-K`. The reset log is written to
`.generated/kubespray/production/kubespray-reset.log`.

To validate privilege escalation before reset, run:

```bash
ansible all \
  -i .generated/kubespray/production/inventory.ini \
  --private-key /home/sysadmin/.ssh/esxi_ansible_ed25519 \
  -b \
  -m command -a 'whoami' -K
```

The become test must return `root` on every node. After reset, verify the source
inventory contains the new node IPs, remove the generated Kubespray output, and
confirm SSH reaches every node:

```bash
OLD_API_IP=172.16.6.9
grep -R "${OLD_API_IP}" inventories/production || true
rm -rf .generated/kubespray/production

ansible managed_vms -m ping --private-key /home/sysadmin/.ssh/esxi_ansible_ed25519
ansible managed_vms -m command -a 'ip -brief addr show ens33' \
  --private-key /home/sysadmin/.ssh/esxi_ansible_ed25519
```

Deploy again from the wrapper so the inventory, Kubespray variables, client
artifacts, kube-vip, and MetalLB settings are rendered from the repository:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e kubespray_control_enable_deploy_output_hidden=false -K

ansible-playbook playbooks/13-kubespray-metallb.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -K

ansible-playbook playbooks/14-kubernetes-health.yml \
  -e kubernetes_health_enable_lb_smoke_test=true \
  -e kubernetes_health_enable_warning_event_failure=true
```

End-to-end Kubernetes path after Packer has built all managed VMs:

```bash
ansible-playbook playbooks/99-kubernetes-site.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e kubespray_control_enable_cluster_deploy=true
```

The end-to-end playbook powers on managed VMs, bootstraps guests, enables IPv4
forwarding required by Kubespray, renders inventory, installs Kubespray, and
then runs the Kubespray `cluster.yml` playbook.

The deploy playbook first regenerates the Kubespray inventory, then runs:

```bash
ESXI_IAC_DIR=/home/sysadmin/esxi-ansible-iac
cd /opt/kubespray

/opt/kubespray/.venv/bin/ansible-playbook \
  -i "${ESXI_IAC_DIR}/.generated/kubespray/production/inventory.ini" \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  cluster.yml \
  -b -v
```

The generated Kubespray defaults are intentionally small:

```yaml
container_manager: containerd
kube_network_plugin: calico
kube_proxy_mode: ipvs
kube_proxy_strict_arp: true
kube_vip_enabled: true
kube_vip_controlplane_enabled: true
kube_vip_services_enabled: false
kube_vip_arp_enabled: true
kube_vip_address: 172.16.6.150
kube_vip_interface: ens33
loadbalancer_apiserver:
  address: 172.16.6.150
  port: 6443
dns_mode: coredns
kubelet_rotate_server_certificates: true
kubelet_csr_approver_values:
  providerRegex: '^ubuntu-24-04-(mgmt|wrk)-0[1-3]$'
  providerIpPrefixes: '172.16.6.20/32,172.16.6.21/32,172.16.6.22/32,172.16.6.23/32,172.16.6.24/32,172.16.6.25/32'
  bypassDnsResolution: false
  bypassHostnameCheck: false
kube_service_addresses: 10.233.0.0/18
kube_pods_subnet: 10.233.64.0/18
calico_datastore: kdd
calico_network_backend: vxlan
calico_ipip_mode: Never
calico_vxlan_mode: Always
kubeconfig_localhost: true
kubectl_localhost: true
```

### Kubelet And Metrics Server TLS

Production enables kubelet serving-certificate rotation and requires Metrics
Server to verify each kubelet certificate:

```yaml
kubespray_inventory_enable_kubelet_server_certificate_rotation: true
kubespray_inventory_enable_metrics_server_kubelet_insecure_tls: false
kubespray_inventory_enable_metrics_server_apiservice_insecure_skip_tls_verify: true
```

These settings cover two independent TLS connections. Metrics Server verifies
the CA-signed kubelet certificates, while the APIService skips verification of
Metrics Server's ephemeral localhost serving certificate. Kubespray v2.31.0
uses `metrics_server_kubelet_insecure_tls` for both connections; the deployment
wrapper therefore restores the APIService setting after each Kubespray run.
This matches the upstream Metrics Server manifest and does not add the
`--kubelet-insecure-tls` argument.

Metrics Server also runs with explicit resources and a less fragile probe
timeout in production:

```yaml
kubespray_inventory_metrics_server_requests_cpu: "100m"
kubespray_inventory_metrics_server_requests_memory: "200Mi"
kubespray_inventory_metrics_server_limits_cpu: "300m"
kubespray_inventory_metrics_server_limits_memory: "300Mi"
kubespray_metrics_server_probe_timeout_seconds: 5
```

The requests match the upstream baseline for clusters up to 100 nodes. The CPU
limit is raised above the default `100m` ceiling because this VMware cluster has
shown intermittent one-second readiness and liveness timeout failures during
control-plane or node pressure. The Kubespray inventory persists the resource
values, and the deployment wrapper reconciles the live deployment's liveness and
readiness `timeoutSeconds` after each Kubespray run.

For end-to-end verification, issue Metrics Server a serving certificate with
`metrics-server.kube-system.svc` in its DNS SAN, publish the signer CA through
`APIService.spec.caBundle`, and set the APIService compatibility option to
`false`. That certificate lifecycle is intentionally not added here because
Kubespray's built-in Metrics Server addon does not manage it.

Kubespray writes the active kubelet configuration to
`/etc/kubernetes/kubelet-config.yaml`. Every node must have both
`rotateCertificates: true` and `serverTLSBootstrap: true`; the similarly named
`/var/lib/kubelet/config.yaml` is not the active configuration in this
deployment. The kubelet process identifies the authoritative file through its
`--config` argument.

The CSR approver policy allows only the six production node names and their
exact `/32` addresses. DNS and hostname checks remain enabled. Before adding,
renaming, or renumbering a node, update its forward DNS record and both policy
allowlists, deploy the approver policy, and only then start or join the node.
Treat Pending or Denied kubelet-serving CSRs as a failed rollout; do not bypass
DNS resolution or hostname validation.

Before enforcing strict Metrics Server-to-kubelet verification, verify the
active kubelet setting and the live certificate on every node:

```bash
ansible managed_vms -b -m shell -a '
grep -E "serverTLSBootstrap|rotateCertificates" \
  /etc/kubernetes/kubelet-config.yaml
'

for ip in 172.16.6.{20..25}; do
  curl --cacert /etc/kubernetes/ssl/ca.crt \
    --connect-timeout 5 -sS -o /dev/null \
    -w "${ip} HTTP=%{http_code}\n" \
    "https://${ip}:10250/healthz"
done
```

Each endpoint must return HTTP `401` or `403` without an X.509 error. These
responses prove TLS verification succeeded and unauthenticated access was
rejected. After deployment, confirm Metrics Server no longer has the
`--kubelet-insecure-tls` argument and that the aggregated API remains healthy:

```bash
kubectl -n kube-system get deployment metrics-server \
  -o jsonpath='{.spec.template.spec.containers[0].args}{"\n"}'
kubectl -n kube-system get deployment metrics-server \
  -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}{.spec.template.spec.containers[0].livenessProbe.timeoutSeconds}{"\n"}{.spec.template.spec.containers[0].readinessProbe.timeoutSeconds}{"\n"}'
kubectl -n kube-system rollout status deployment/metrics-server
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl get apiservice v1beta1.metrics.k8s.io \
  -o jsonpath='{.spec.insecureSkipTLSVerify}{"\n"}'
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
kubectl top nodes
```

The health playbook waits for the Metrics API to return one node-metrics object
for every managed Kubernetes node. This covers Metrics Server's normal startup
delay and prevents a partially populated metrics cache from passing validation.

If strict verification fails, restore
`kubespray_inventory_enable_metrics_server_kubelet_insecure_tls: true` in the source inventory
and redeploy. Do not weaken the CSR approver policy. Metrics Server remains at
Kubespray's default single replica, and aggregator routing is not enabled.

After a successful Kubespray wrapper run, the local `admin.conf` artifact is
also installed as `~/.kube/config` for the `sysadmin` automation user. This
keeps normal `kubectl` commands from falling back to `localhost:8080`.
The wrapper also installs each control-plane node's
`/etc/kubernetes/admin.conf` as `~/.kube/config` for the same automation user
on every control-plane node, so `kubectl` works consistently from
`ubuntu-24-04-mgmt-01`, `ubuntu-24-04-mgmt-02`, and `ubuntu-24-04-mgmt-03`.
The health playbook repeats this idempotently, so rerunning
`playbooks/14-kubernetes-health.yml` also repairs missing control-plane
user kubeconfigs without a full cluster redeploy.

The pod and service CIDRs are pinned to unused ranges outside the
`172.16.6.0/24` VM network. VXLAN is pinned to Kubespray's supported default;
ensure UDP `4789` is permitted between every cluster node. MTU remains
auto-detected because the correct value depends on the ESXi network underlay.
On the VMware-backed Ubuntu guests, the production inventory also disables
GRO/LRO and UDP tunnel offloads on `ens33` with a small systemd service. This
keeps Calico VXLAN decapsulation stable after node reboots; otherwise MetalLB
webhook traffic can reach the target node on UDP `4789` but never reach the
controller pod.

kube-vip owns only the highly available Kubernetes API endpoint at
`172.16.6.150:6443`. Reserve `172.16.6.150` outside DHCP before deployment.
Service mode stays disabled so MetalLB remains the only controller assigning
application and ingress `LoadBalancer` addresses from `172.16.6.200-172.16.6.250`.

The generated Kubespray addon file is written only with enabled addons:

```text
.generated/kubespray/production/group_vars/k8s_cluster/addons.yml
```

MetalLB is enabled in the production inventory. The initial `cluster.yml` run
installs the MetalLB controller and speaker. After the cluster is stable,
apply the `IPAddressPool` and `L2Advertisement` custom resources with the
dedicated MetalLB playbook. The production pool is reserved as
`172.16.6.200-172.16.6.250`, separate from the kube-vip API address
`172.16.6.150`.

```bash
ansible-playbook playbooks/13-kubespray-metallb.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -K
```

Run this playbook as `sysadmin`, not from a root shell. The wrapper uses
`become` only where Kubespray needs privilege escalation, which keeps generated
`kubectl` and `admin.conf` artifacts usable by the automation user. Override
`kubespray_inventory_metallb_ip_range` only when intentionally changing the reserved
LoadBalancer pool.

For investigation, add `-e kubespray_metallb_debug=true` to print MetalLB
pods, services, endpoints, pools, warning events, and controller/speaker logs.
The memberlist secret remains hidden from Ansible output.

```bash
ansible-playbook playbooks/13-kubespray-metallb.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e kubespray_metallb_debug=true \
  -K
```

This playbook re-renders the Kubespray inventory, runs Kubespray `cluster.yml`
with the `metallb` tag to ensure the controller and speaker are current, then
applies the `IPAddressPool` and `L2Advertisement` resources after the
controller reports ready, the validating webhook CA bundle is injected, and
the webhook service has endpoints. The pre-apply health stage validates
MetalLB controller reachability but intentionally skips address-pool existence
until this playbook has created the pool resources. If the `memberlist` secret was not
auto-created by the controller (a known race in tagged runs), the playbook
creates it and restarts the speaker DaemonSet before proceeding. A server-side
dry-run validates that the webhook is actually responding before the real
apply. This avoids the webhook timeout race that can happen when pool
resources are applied immediately. Nested Kubespray output remains visible for
this targeted operation; the deployment log is also written under
`.generated/kubespray/production/`.

For single-node or lab storage only, enable Rancher local-path provisioner:

```bash
ansible-playbook playbooks/99-kubernetes-site.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e kubespray_control_enable_cluster_deploy=true \
  -e kubespray_inventory_enable_local_path_provisioner=true
```

Local-path storage is not highly available. For production workloads, prefer a
real CSI driver or external storage platform.

### Longhorn V1 Production Storage

Longhorn v1.12.0 provides replicated block storage on the three worker nodes in
the `longhorn_nodes` inventory group. Control-plane nodes do not run Longhorn
components or store replicas.

#### Configuration Policy

| Setting | Production value | Operational effect |
| --- | --- | --- |
| Data engine | V1 enabled, V2 disabled | Uses the stable iSCSI-based engine; SPDK prerequisites are unnecessary. |
| Data path | `/var/lib/longhorn` | Uses each worker's dedicated 500 GiB ext4 disk. |
| Replica count | `3` | Places one synchronous replica on each eligible worker. |
| Node anti-affinity | Strict | Two replicas cannot share a node. |
| Degraded creation | Disabled | New volumes wait when fewer than three eligible workers are available. |
| Data locality | Best effort | Prefers a replica beside the workload without pinning it there. |
| Free-space reserve | 25% | Stops new replica scheduling before a disk is critically full. |
| Over-provisioning | 100% | Limits scheduled volume capacity to the disk's nominal capacity. |
| Reclaim policy | `Retain` | Deleting a production PVC does not automatically destroy its volume data. |
| Default StorageClass | `longhorn` | Longhorn is the intentional default; only one cluster StorageClass may be default. |
| Component placement | Storage-node label | Keeps all user and system-managed Longhorn components off control-plane nodes. |

Three replicas protect against a worker failure only when the worker VMs and
their virtual disks occupy independent ESXi and datastore failure domains.
Longhorn replication is not a backup.

#### 1. Reconcile Storage Nodes

The role installs `open-iscsi`, `nfs-common`, `cryptsetup`, `dmsetup`, and the
required utilities; starts `iscsid`; loads `iscsi_tcp`, `dm_crypt`, and `nfs`;
checks NFSv4.1 and kubelet mount propagation; and manages UUID-based disk
mounts. Per-host variables pin each data disk by `/dev/disk/by-id/scsi-*`.

Production uses single-path VMware virtual disks and no multipath maps. The
production group therefore masks `multipathd.service` and `multipathd.socket`.
Never enable that policy on nodes using SAN multipath storage.

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519

# Prove idempotency. Every worker must report changed=0 and failed=0.
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519

ansible longhorn_nodes -b -m shell -a '
set -e
findmnt -rn -T /var/lib/longhorn -o SOURCE,FSTYPE,OPTIONS
test -w /var/lib/longhorn
systemctl is-active iscsid.service
systemctl is-active multipathd.service | grep -qx inactive
'
```

#### 2. Create the Namespace and Run Preflight

Longhorn requires privileged host access. Keep that exception isolated in the
dedicated namespace:

```bash
kubectl apply -f helm/longhorn/namespace.yaml

test -x "$HOME/longhornctl" || {
  curl -sSfL -o "$HOME/longhornctl" \
    https://github.com/longhorn/cli/releases/download/v1.12.0/longhornctl-linux-amd64
  chmod 0755 "$HOME/longhornctl"
}

"$HOME/longhornctl" version
"$HOME/longhornctl" --kubeconfig "$HOME/.kube/config" check preflight
```

The CLI version must be `v1.12.0`. Proceed only when every worker has no
`error` or `warn` section. The preflight checker creates temporary resources in
`longhorn-system`, which is why the namespace must exist first.

#### 3. Opt In Storage Workers

Apply both labels before installing Longhorn. The first controls Kubernetes pod
placement. The second permits creation of the default Longhorn disk because
`createDefaultDiskLabeledNodes` is enabled.

```bash
for node in \
  ubuntu-24-04-wrk-01 ubuntu-24-04-wrk-02 ubuntu-24-04-wrk-03; do
  kubectl label node "$node" \
    node-role.kubernetes.io/storage=true \
    node.longhorn.io/create-default-disk=true \
    --overwrite
done

kubectl get nodes -l node-role.kubernetes.io/storage=true \
  -o custom-columns='NAME:.metadata.name,DISK:.metadata.labels.node\.longhorn\.io/create-default-disk'
```

Exactly three workers must be returned. `global.nodeSelector` places the
Manager, Driver, and UI on these nodes; `systemManagedComponentsNodeSelector`
applies the same constraint to instance managers, share managers, CSI pods,
engine images, and other Longhorn-managed components.

#### 4. Render the Pinned Chart

```bash
kubectl get storageclass \
  -o custom-columns='NAME:.metadata.name,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class'

helm repo add longhorn https://charts.longhorn.io --force-update
helm repo update longhorn
helm show chart longhorn/longhorn --version 1.12.0

helm template longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --version 1.12.0 \
  --values helm/longhorn/values-production.yaml \
  > /tmp/longhorn-rendered.yaml

test -s /tmp/longhorn-rendered.yaml
grep -q 'node-role.kubernetes.io/storage' /tmp/longhorn-rendered.yaml
grep -q '/var/lib/longhorn' /tmp/longhorn-rendered.yaml
```

Resolve any existing default StorageClass before installation. Kubernetes
permits multiple defaults but selects the most recently created one, which is
ambiguous for operators and workloads.

Review `helm/longhorn/values-production.yaml` and the rendered diff before each
install or upgrade. StorageClass parameter changes affect only newly created
volumes; they do not rewrite existing volumes.

#### 5. Install Longhorn

```bash
helm upgrade --install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --version 1.12.0 \
  --values helm/longhorn/values-production.yaml \
  --atomic --timeout 15m
```

`--atomic` removes or rolls back a failed Helm release, but installed CRDs can
remain. Do not manually delete Longhorn CRDs as failure cleanup.

#### 6. Validate Installation

```bash
helm -n longhorn-system status longhorn
kubectl -n longhorn-system get pods -o wide
kubectl -n longhorn-system get nodes.longhorn.io
kubectl -n longhorn-system get volumes.longhorn.io
kubectl -n longhorn-system get settings.longhorn.io \
  default-data-path default-replica-count \
  create-default-disk-labeled-nodes \
  allow-volume-creation-with-degraded-availability \
  v1-data-engine v2-data-engine

kubectl get storageclass \
  -o custom-columns='NAME:.metadata.name,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class,PROVISIONER:.provisioner,RECLAIM:.reclaimPolicy'
```

Require all Longhorn pods to be healthy, three Longhorn nodes to be schedulable,
and one ready disk at `/var/lib/longhorn` per node. Confirm that exactly one
StorageClass is marked default before onboarding workloads.

#### 7. Run Disposable RWO and RWX Tests

The smoke manifest creates a temporary StorageClass with `Delete` reclaim
policy so cleanup does not leave retained test volumes:

```bash
kubectl apply -f helm/longhorn/smoke-test.yaml
kubectl -n longhorn-smoke wait \
  --for=jsonpath='{.status.phase}'=Bound pvc --all --timeout=5m
kubectl -n longhorn-smoke wait --for=condition=Ready pod --all --timeout=10m

kubectl -n longhorn-smoke exec pod/longhorn-rwo -- cat /data/result
kubectl -n longhorn-smoke get pods -o wide
kubectl -n longhorn-smoke exec deploy/longhorn-rwx -- sh -ec \
  'test "$(find /data -maxdepth 1 -type f | wc -l)" -ge 2'

SMOKE_PVS=$(kubectl get pv \
  -o jsonpath='{range .items[?(@.spec.storageClassName=="longhorn-smoke")]}{.metadata.name}{" "}{end}')

kubectl delete namespace longhorn-smoke --wait=true

for pv in $SMOKE_PVS; do
  kubectl wait --for=delete "pv/$pv" --timeout=5m
done

kubectl delete storageclass longhorn-smoke
```

Expected results are `rwo-ok`, two RWX pods on different workers, and no
remaining `longhorn-smoke` PV after cleanup. Keep the temporary StorageClass
until CSI finishes deleting its PVs; never remove Longhorn or Kubernetes
finalizers to accelerate normal cleanup.

#### 8. Production Acceptance

Before storing production data:

1. Create and restore an encrypted test volume using a secret supplied by the
   deployment secret manager. Never commit LUKS keys or passphrases.
2. Configure an external S3-compatible or NFSv4 backup target outside this
   Kubernetes cluster and its ESXi failure domain.
3. Complete a backup and restore test; snapshots alone are not backups.
4. Add capacity, node, replica health, and backup-failure monitoring.
5. Run `playbooks/14-kubernetes-health.yml` and require no new warning events.

Production PVC deletion is intentionally non-destructive because the default
StorageClass uses `Retain`. Releasing storage therefore requires an explicit,
reviewed PV and Longhorn volume deletion procedure.

#### Replacement Disk Procedure

Disk formatting is destructive and is not part of installation or routine
reconciliation. After attaching a blank replacement disk, record its stable
`/dev/disk/by-id/scsi-*` path in the node's `host_vars/longhorn.yml`. Verify it
is unpartitioned and is not the root disk, then authorize formatting for that
single host only:

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --limit ubuntu_24.04-wrk-REPLACE \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e longhorn_node_prepare_enable_disk_format=true
```

Never persist `longhorn_node_prepare_enable_disk_format: true`. Before replacing
a disk that Longhorn already manages, first disable scheduling and safely evict
its replicas through Longhorn.

References:

- <https://longhorn.io/docs/1.12.0/deploy/install/>
- <https://longhorn.io/docs/1.12.0/deploy/install/install-with-helm/>
- <https://longhorn.io/docs/1.12.0/best-practices/>
- <https://longhorn.io/docs/1.12.0/advanced-resources/deploy/node-selector/>
- <https://longhorn.io/docs/1.12.0/nodes-and-volumes/nodes/default-disk-and-node-config/>
- <https://longhorn.io/docs/1.12.0/references/storage-class-parameters/>
- <https://kubernetes.io/docs/concepts/storage/storage-classes/>

Keep these values in `inventories/production/group_vars/all.yml`, not in the
generated `.generated/` files.

Before rerunning addon phases after a partial install, verify the cluster:

```bash
ansible-playbook playbooks/14-kubernetes-health.yml
```

The health check includes `metrics.k8s.io` availability and cert-manager
webhook readiness, which catches stale discovery and CA-injection timing
issues before addon retries.

Health-check hints:

1. Reconfirm live health from the control node with `kubectl get nodes`,
   `kubectl get apiservice v1beta1.metrics.k8s.io`, and `kubectl top nodes`.
2. Re-run `playbooks/14-kubernetes-health.yml` after any cluster change so the
   readiness checks stay aligned with the current cluster state.

### Post-Deploy Kubernetes Health Checklist

Run this checklist after the initial Kubespray deployment, after addon changes,
and after any node reboot or ESXi network change. The first command also
repairs missing `~/.kube/config` files on the control-plane nodes.

```bash
cd ~/esxi-ansible-iac
ansible-playbook playbooks/14-kubernetes-health.yml
```

For a deeper production smoke test, include the temporary LoadBalancer check and
turn warning events into a hard failure:

```bash
ansible-playbook playbooks/14-kubernetes-health.yml \
  -e kubernetes_health_enable_lb_smoke_test=true \
  -e kubernetes_health_enable_warning_event_failure=true
```

The warning-event gate separates old retained events from active incidents. By
default, the role shows the full retained Warning event list for audit context
but only fails production readiness on Warning events seen in the last 15
minutes. Adjust the active window if you are investigating a longer outage:

```bash
ansible-playbook playbooks/14-kubernetes-health.yml \
  -e kubernetes_health_enable_warning_event_failure=true \
  -e kubernetes_health_warning_event_active_window_minutes=30
```

Verify the API server and registered nodes:

```bash
kubectl cluster-info
kubectl get nodes -o wide
kubectl get --raw=/readyz
kubectl get --raw=/livez
```

Verify kube-system rollouts:

```bash
kubectl -n kube-system get pods -o wide
kubectl -n kube-system rollout status daemonset/calico-node --timeout=180s
kubectl -n kube-system rollout status daemonset/kube-proxy --timeout=180s
kubectl -n kube-system rollout status deployment/calico-kube-controllers --timeout=180s
kubectl -n kube-system rollout status deployment/coredns --timeout=180s
kubectl -n kube-system rollout status daemonset/nodelocaldns --timeout=180s
```

Verify DNS from inside the cluster:

```bash
kubectl -n default run dns-test \
  --rm -it --restart=Never \
  --image=busybox:1.36 \
  -- nslookup kubernetes.default.svc.cluster.local

kubectl -n default run dns-test-public \
  --rm -it --restart=Never \
  --image=busybox:1.36 \
  -- nslookup archive.ubuntu.com
```

Verify the Metrics API:

```bash
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl -n kube-system get deployment metrics-server \
  -o custom-columns='NAME:.metadata.name,REQ_CPU:.spec.template.spec.containers[0].resources.requests.cpu,REQ_MEM:.spec.template.spec.containers[0].resources.requests.memory,LIMIT_CPU:.spec.template.spec.containers[0].resources.limits.cpu,LIMIT_MEM:.spec.template.spec.containers[0].resources.limits.memory,LIVE_TIMEOUT:.spec.template.spec.containers[0].livenessProbe.timeoutSeconds,READY_TIMEOUT:.spec.template.spec.containers[0].readinessProbe.timeoutSeconds'
kubectl top nodes
kubectl top pods -A
```

Verify cert-manager readiness before applying certificate-dependent resources:

```bash
kubectl -n cert-manager get pods -o wide
kubectl -n cert-manager rollout status deployment/cert-manager --timeout=180s
kubectl -n cert-manager rollout status deployment/cert-manager-cainjector --timeout=180s
kubectl -n cert-manager rollout status deployment/cert-manager-webhook --timeout=180s
kubectl get validatingwebhookconfiguration cert-manager-webhook -o jsonpath='{.webhooks[*].clientConfig.caBundle}{"\n"}'
kubectl -n cert-manager get endpoints cert-manager-webhook -o wide
kubectl get clusterissuer k8s-internal-ca
kubectl -n cert-manager get secret k8s-internal-root-ca-secret
```

If `k8s-internal-ca` is not `Ready=True`, do not apply certificate-dependent
workloads. First restore or recreate the root CA Secret, then wait for
cert-manager to reconcile the ClusterIssuer.

If the internal root CA Secret was recreated, renew the user-facing ingress
certificates first, then rotate the PostgreSQL server certificate separately.
CNPG and database clients are more sensitive to TLS changes than UI workloads.

Inspect the current PostgreSQL server certificate before rotation:

```bash
kubectl -n database get cluster postgres-prod
kubectl -n database get pods -o wide
kubectl -n database get certificate postgres-prod-server -o yaml

kubectl -n database get secret postgres-prod-server-tls \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  openssl x509 -noout -subject -issuer -ext subjectAltName -dates
```

Only continue when the CNPG cluster is healthy and all instances are ready.
Renew the server certificate through cert-manager:

```bash
kubectl -n database delete secret postgres-prod-server-tls --ignore-not-found

kubectl -n database annotate certificate postgres-prod-server \
  cert-manager.io/renew-reason="renew after internal root CA rotation $(date -Iseconds)" \
  --overwrite

kubectl -n database wait certificate postgres-prod-server \
  --for=condition=Ready \
  --timeout=180s
```

Verify the renewed certificate issuer and SANs:

```bash
kubectl -n database get secret postgres-prod-server-tls \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  openssl x509 -noout -subject -issuer -ext subjectAltName -dates
```

Check that CNPG observed the Secret version change:

```bash
kubectl -n database describe cluster postgres-prod | grep -A20 "Secrets Resource Version"
kubectl -n database get pods -o wide
```

If PostgreSQL needs a reload and the CNPG plugin is installed, reload through
the plugin:

```bash
kubectl cnpg reload -n database postgres-prod
```

If the plugin is not available, perform a controlled CNPG restart window:

```bash
kubectl -n database annotate cluster postgres-prod \
  cnpg.io/restartedAt="$(date -Iseconds)" \
  --overwrite

kubectl -n database get cluster postgres-prod -w
kubectl -n database get pods -w
```

After the rotation settles, confirm health again:

```bash
kubectl -n database get cluster postgres-prod
kubectl -n database get pods
kubectl -n database describe cluster postgres-prod | grep -A30 "Conditions"
```

Any external or application-side PostgreSQL clients that verify server TLS must
trust the renewed internal root CA before this rotation is considered complete.

Verify Calico VXLAN state and the VMware NIC offload workaround:

```bash
ansible managed_vms -b -m shell \
  -a 'hostname; ip link show vxlan.calico; ss -lunp | grep 4789 || true; ip route | grep calico || true' \
  --private-key ~/.ssh/esxi_ansible_ed25519

ansible managed_vms -b -m shell \
  -a 'hostname; ethtool -k ens33 | grep -Ei "generic-receive-offload|large-receive-offload|tx-udp_tnl"' \
  --private-key ~/.ssh/esxi_ansible_ed25519
```

Expected offload state on every Kubernetes node:

```text
generic-receive-offload: off
large-receive-offload: off
tx-udp_tnl-segmentation: off
tx-udp_tnl-csum-segmentation: off
```

Verify MetalLB components, pool resources, and webhook reachability:

```bash
kubectl -n metallb-system get pods -o wide
kubectl -n metallb-system get svc,endpoints,endpointslices -o wide
kubectl -n metallb-system get ipaddresspools,l2advertisements -o wide

METALLB_WEBHOOK_IP="$(kubectl -n metallb-system get svc webhook-service \
  -o jsonpath='{.spec.clusterIP}')"

ansible ubuntu_24.04-mgmt-01,ubuntu_24.04-mgmt-02,ubuntu_24.04-mgmt-03 \
  -m uri \
  -a "url=https://${METALLB_WEBHOOK_IP}:443/ validate_certs=false use_proxy=false timeout=5 status_code=200,400,404,405" \
  --private-key ~/.ssh/esxi_ansible_ed25519
```

The MetalLB webhook URI check should return a successful Ansible task with HTTP
`404`. That status is acceptable for `/`; it proves the service path is
reachable.

Validate an actual `LoadBalancer` allocation:

```bash
kubectl create deployment nginx-lb-test --image=nginx:1.27
kubectl expose deployment nginx-lb-test --type=LoadBalancer --port=80
kubectl get svc nginx-lb-test -w
```

After the service receives an external IP from
`172.16.6.200-172.16.6.250`, test and clean up:

```bash
EXTERNAL_IP="$(kubectl get svc nginx-lb-test \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"

curl "http://${EXTERNAL_IP}"
kubectl delete svc nginx-lb-test
kubectl delete deployment nginx-lb-test
```

Review cluster warnings and non-running pods:

```bash
kubectl get events -A --field-selector=type=Warning --sort-by=.metadata.creationTimestamp
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
```

#### Migrate kube-proxy from IPVS to nftables

Kubernetes may report `IPVSDeprecation` events when `kube_proxy_mode` is
`ipvs`. Treat migration to `nftables` as a planned service-networking change
because kube-proxy handles Kubernetes Service routing for the whole cluster.
Run it in a maintenance window and confirm an etcd backup exists first.

Capture the current baseline before changing the mode:

```bash
kubectl get nodes -o wide
kubectl -n kube-system get configmap kube-proxy \
  -o jsonpath='{.data.config\.conf}' |
  grep -n -E 'mode:|metricsBindAddress|healthzBindAddress'
kubectl get svc -A --field-selector spec.type=LoadBalancer
curl -s "https://prometheus.k8s.tss.local/api/v1/targets?state=any" | jq -r '
  .data.activeTargets[]
  | select(.labels.job | test("kube-proxy|proxy"; "i"))
  | [.health, .scrapeUrl, .lastError] | @tsv
'
kubectl get events -A --field-selector=type=Warning --sort-by=.metadata.creationTimestamp
```

Verify Kubespray and the nodes support nftables:

```bash
grep -Rni "nftables" /opt/kubespray/roles /opt/kubespray/inventory | head -80

ansible k8s_cluster -b -m shell -a '
hostname
uname -r
command -v nft
nft --version
lsmod | grep -E "nf_tables|nft_|nf_conntrack" || true
'
```

Change the source inventory from IPVS to nftables:

```bash
cd ~/esxi-ansible-iac

sed -i 's/kubespray_inventory_kube_proxy_mode: ipvs/kubespray_inventory_kube_proxy_mode: nftables/' \
  inventories/production/group_vars/all.yml
```

Render and confirm the generated Kubespray inventory:

```bash
ansible-playbook playbooks/07-kubespray-inventory.yml

grep -n "kube_proxy_mode" \
  .generated/kubespray/production/group_vars/k8s_cluster/k8s-cluster.yml
```

Expected:

```text
kube_proxy_mode: "nftables"
```

Run a full Kubespray apply. Do not use a narrow `kube-proxy` tag for this
migration; tagged runs can skip Kubespray variable setup tasks:

```bash
export KUBESPRAY_BECOME_PASSWORD="$(cat /tmp/password-file)"

nohup ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e kubespray_control_enable_deploy_output_hidden=false \
  > kubespray-nftables-migration.log 2>&1 &

tail -f kubespray-nftables-migration.log
```

After Kubespray completes, verify kube-proxy and service routing:

```bash
kubectl -n kube-system rollout status daemonset/kube-proxy --timeout=180s

kubectl -n kube-system get configmap kube-proxy \
  -o jsonpath='{.data.config\.conf}' |
  grep -n -E 'mode:|metricsBindAddress|healthzBindAddress'

ansible k8s_cluster -b -m shell -a \
  "ss -lntp | grep -E ':10249|:10256' || true"

kubectl get nodes
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get svc -A --field-selector spec.type=LoadBalancer
curl -k https://traefik.k8s.tss.local
curl -k https://prometheus.k8s.tss.local/-/ready
```

Expected kube-proxy config after migration:

```text
mode: nftables
metricsBindAddress: 0.0.0.0:10249
```

Confirm Prometheus can still scrape kube-proxy:

```bash
curl -s "https://prometheus.k8s.tss.local/api/v1/targets?state=any" | jq -r '
  .data.activeTargets[]
  | select(.labels.job | test("kube-proxy|proxy"; "i"))
  | [.health, .scrapeUrl, .lastError] | @tsv
'
```

Then run the full health gate, including the LoadBalancer smoke test:

```bash
ansible-playbook playbooks/14-kubernetes-health.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e kubernetes_health_enable_lb_smoke_test=true \
  -e kubernetes_health_enable_warning_event_failure=true \
  -e kubernetes_health_kube_vip_max_restarts=21
```

If Kubespray finishes but the live `kube-proxy` ConfigMap still reports
`mode: ipvs`, stop and inspect the generated inventory, Kubespray logs, and
Kubespray kubeadm template behavior before manually patching the mode. Unlike
the metrics bind address, kube-proxy mode changes service routing cluster-wide.

#### Kubernetes Cleanup and Prune Concepts

Kubernetes does not have one safe equivalent to `docker system prune -a`.
Cluster cleanup should be targeted because many Kubernetes objects are live
desired state, and storage objects may contain production data.

Core cleanup concepts:

- Pods are disposable runtime objects, but only completed or failed standalone
  pods should be deleted manually. Pods owned by Deployments, DaemonSets,
  StatefulSets, Jobs, or operators will be recreated from their controller.
- Jobs are workload history. Delete completed Jobs only after their logs and
  results are no longer needed.
- ReplicaSets with zero desired, zero current, and zero ready pods are old
  Deployment rollout history. They can usually be removed after rollback is no
  longer needed.
- PVCs, PVs, VolumeAttachments, and Longhorn volumes are data-plane objects.
  Do not delete them as routine cleanup. For this cluster, the `longhorn` and
  `longhorn-cnpg` StorageClasses use `Retain`, so deleting a PVC intentionally
  leaves storage behind for reviewed recovery or deletion.
- Container images live on each node, not in the Kubernetes API. Prune unused
  images with the container runtime (`crictl`) after verifying the cluster is
  healthy.

Start with a dry inventory of obvious cleanup candidates:

```bash
kubectl get pods -A --field-selector=status.phase=Succeeded
kubectl get pods -A --field-selector=status.phase=Failed
kubectl get jobs -A
kubectl get rs -A
kubectl get pvc -A
kubectl get pv
```

Clean completed or failed pods when they exist:

```bash
kubectl delete pod -A --field-selector=status.phase=Succeeded
kubectl delete pod -A --field-selector=status.phase=Failed
```

Clean completed Jobs when their logs are no longer needed:

```bash
kubectl get jobs -A -o jsonpath='{range .items[?(@.status.succeeded==1)]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}' |
  while read ns name; do
    kubectl -n "$ns" delete job "$name"
  done
```

Clean unused ReplicaSets with no desired, current, or ready pods:

```bash
kubectl get rs -A --no-headers | awk '$3 == 0 && $4 == 0 && $5 == 0 {print $1, $2}' |
  while read ns name; do
    kubectl -n "$ns" delete rs "$name"
  done
```

Inspect node images before pruning:

```bash
ansible managed_vms -b -m shell -a 'crictl images' \
  --private-key ~/.ssh/esxi_ansible_ed25519
```

Prune unused container images node by node. This removes images that are not
used by any current container on that node:

```bash
ansible ubuntu_24.04-wrk-01 -b -m shell -a 'crictl rmi --prune' \
  --private-key ~/.ssh/esxi_ansible_ed25519
ansible ubuntu_24.04-wrk-02 -b -m shell -a 'crictl rmi --prune' \
  --private-key ~/.ssh/esxi_ansible_ed25519
ansible ubuntu_24.04-wrk-03 -b -m shell -a 'crictl rmi --prune' \
  --private-key ~/.ssh/esxi_ansible_ed25519
```

If a `crictl rmi --prune` run reports `DeadlineExceeded` or `RST_STREAM` while
removing images, stop and verify cluster health before retrying. Do not keep
rerunning image pruning against a busy production cluster.

After any cleanup, verify that the cleanup did not create new symptoms:

```bash
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get events -A --field-selector=type=Warning
kubectl top nodes
```

Review kube-vip after any API interruption:

```bash
kubectl -n kube-system get pods -l k8s-app=kube-vip \
  -o custom-columns='POD:.metadata.name,NODE:.spec.nodeName,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount'
kubectl -n kube-system logs -l k8s-app=kube-vip --since=2h --all-containers
kubectl -n kube-system logs -l k8s-app=kube-vip --previous --all-containers
```

If kube-vip restart counts are already known to be historical, run the health
check with the current maximum restart baseline instead of the default zero.
For the July 22, 2026 validation, the observed stable baseline was:

```text
kube-vip-ubuntu-24-04-mgmt-01: 13
kube-vip-ubuntu-24-04-mgmt-02: 19
kube-vip-ubuntu-24-04-mgmt-03: 21
```

Use the maximum value when rerunning production health:

```bash
ansible-playbook playbooks/14-kubernetes-health.yml \
  --private-key ~/.ssh/esxi_ansible_ed25519 \
  -e kubernetes_health_enable_warning_event_failure=true \
  -e kubernetes_health_kube_vip_max_restarts=21
```

Then observe that the counters do not increase:

```bash
watch -n 60 'kubectl -n kube-system get pods -l k8s-app=kube-vip -o jsonpath="{range .items[*]}{.metadata.name}{\" restarts=\"}{.status.containerStatuses[0].restartCount}{\" started=\"}{.status.containerStatuses[0].state.running.startedAt}{\"\n\"}{end}"'
```

If any kube-vip restart count increases above the documented baseline without
a planned control-plane restart or Kubespray run, pause production validation
and inspect kube-vip logs, kubelet/containerd logs, API server readiness
events, and ESXi/network events before raising the threshold.

For an unexplained cluster-wide interruption, preserve the node logs before
rotation removes the useful window:

```bash
ansible managed_vms -b -m shell -a '
journalctl --since "2026-07-01 00:00:00" --until "2026-07-01 01:00:00" \
  -u kubelet -u containerd --no-pager
dmesg -T | tail -n 300
'
```

Also review ESXi host events, datastore latency, vSwitch/uplink events, VM
stun/snapshot activity, and any management-plane maintenance during the same
time window.

Production readiness also requires operational checks that a live health check
cannot prove by itself:

- Validate an etcd snapshot and restore procedure before storing production
  workloads.
- Test kube-vip API failover by moving or restarting one control-plane node and
  confirming `kubectl get --raw=/readyz` still works through the VIP.
- Drain, reboot, and uncordon one worker node to confirm workload rescheduling
  and Calico VXLAN recovery.
- Confirm monitoring, alerting, and log retention cover node pressure, API
  errors, etcd health, certificate expiry, pod restarts, and LoadBalancer
  failures.
- Apply namespace security baselines, least-privilege RBAC, and required
  NetworkPolicies for application namespaces.
- Confirm backup and restore coverage for application data, persistent volumes,
  GitOps state, and cluster add-on manifests.

Useful preflight checks before deployment:

```bash
ansible managed_vms -m ping --private-key ~/.ssh/esxi_ansible_ed25519

ansible managed_vms -m command -a whoami -b \
  --private-key ~/.ssh/esxi_ansible_ed25519

ansible managed_vms -m shell \
  -a "sshd -T | egrep '^(passwordauthentication|kbdinteractiveauthentication) '" \
  -b \
  --private-key ~/.ssh/esxi_ansible_ed25519
```

After Kubespray finishes, check nodes from the generated artifact:

```bash
cd .generated/kubespray/production/artifacts
./kubectl --kubeconfig admin.conf get nodes -o wide
```

Kubespray v2.31.0 enables NodeLocalDNS by default. This repository explicitly
pins its enabled state, link-local address, and health port so generated
inventory and node-level health checks do not depend on changing defaults.

Full Ansible runtime sequence for an existing Packer-built VM:

```bash
ansible-playbook playbooks/99-site-run.yml \
  -e vm_power_name=ubuntu_24.04-mgmt-01 \
  -e vm_power_state=powered-on
```

## Power Operations

```bash
ansible-playbook playbooks/04-vm-power.yml -e vm_power_name=ubuntu_24.04-mgmt-01 -e vm_power_state=powered-on
ansible-playbook playbooks/04-vm-power.yml -e vm_power_name=ubuntu_24.04-mgmt-01 -e vm_power_state=powered-off
ansible-playbook playbooks/04-vm-power.yml -e vm_power_name=ubuntu_24.04-mgmt-01 -e vm_power_state=restarted
ansible-playbook playbooks/04-vm-power.yml -e vm_power_name=ubuntu_24.04-mgmt-01 -e vm_power_state=shutdown-guest
ansible-playbook playbooks/04-vm-power.yml -e vm_power_name=ubuntu_24.04-mgmt-01 -e vm_power_state=reboot-guest
```

## Host Key Handling

`99-guest-site.yml` waits for TCP/22 before scanning SSH host keys. It does not
remove existing known-host entries by default. If a VM is rebuilt and receives a
new host key at the same IP, force removal once:

```bash
ansible-playbook playbooks/99-guest-site.yml -e ssh_known_hosts_enable_remove_old=true
```

## Delete Safety

Deletion requires both `vm_delete_confirm=true` and a matching `vm_delete_confirm_name`.

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e vm_delete_name=ubuntu_24.04-test-01 \
  -e vm_delete_confirm=true \
  -e vm_delete_confirm_name=ubuntu_24.04-test-01
```

Force deletion is intentionally explicit:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e vm_delete_name=ubuntu_24.04-test-01 \
  -e vm_delete_confirm=true \
  -e vm_delete_confirm_name=ubuntu_24.04-test-01 \
  -e vm_delete_enable_force=true
```

For higher-assurance production deletion, also require the VM UUID shown by the
delete preview:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e vm_delete_name=ubuntu_24.04-test-01 \
  -e vm_delete_confirm=true \
  -e vm_delete_confirm_name=ubuntu_24.04-test-01 \
  -e vm_delete_enable_uuid_confirmation=true \
  -e vm_delete_confirm_uuid=<uuid-from-preview>
```

Delete all VMs in the `managed_vms` inventory group:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e scope=all \
  -e vm_delete_enable_all_confirmation=true \
  -e vm_delete_all_confirmation_phrase=DELETE_ALL_MANAGED_VMS
```

Force delete all managed VMs, including powered-on VMs:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e scope=all \
  -e vm_delete_enable_all_confirmation=true \
  -e vm_delete_all_confirmation_phrase=DELETE_ALL_MANAGED_VMS \
  -e vm_delete_enable_force=true
```

Delete only selected managed VMs by overriding `vm_delete_targets`:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e scope=all \
  -e vm_delete_enable_all_confirmation=true \
  -e vm_delete_all_confirmation_phrase=DELETE_ALL_MANAGED_VMS \
  -e '{"vm_delete_targets":["ubuntu_24.04-mgmt-02","ubuntu_24.04-wrk-02"]}'
```

## Production Notes

- Packer creates and installs Ubuntu VMs.
- Ansible manages ESXi runtime state and guest bootstrap after the VM exists.
- VMware API tasks use fully qualified collection names and run on localhost.
- Sensitive VMware API calls use `no_log: true`.
- `host_key_checking` is enabled.
- `esxi_validate_certs` is enabled. Keep it enabled for production and install
  the ESXi host CA or replace self-signed host certificates instead of disabling
  validation.
- Ubuntu autoinstall currently permits password SSH for Packer and Ansible.
  Prefer SSH keys and disable password SSH after bootstrap with
  `guest_base_enable_password_ssh_disabled=true` for production.
- Kubespray deployment should use SSH keys after password SSH is disabled. The
  control node must be able to reach all Kubernetes nodes, and the nodes must be
  able to pull images unless you configure Kubespray for an offline registry.
- Guest apt cache refresh is throttled by `guest_base_apt_cache_valid_time` to keep
  repeat bootstrap runs idempotent.
