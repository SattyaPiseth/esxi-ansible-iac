# ESXi Ansible IaC

Infrastructure automation for a small, production-style Kubernetes platform on standalone VMware ESXi hosts.

This repository builds Ubuntu 24.04 virtual machines with Packer, configures them with Ansible, deploys Kubernetes with Kubespray, and prepares worker nodes for Longhorn. It also provides guarded ESXi lifecycle operations, cluster networking, and health checks.

## Project ownership

Maintenance reference: [feature ownership matrix](docs/feature-maintenance.md#feature-ownership-matrix).

| Area | Tool | Responsibility |
|---|---|---|
| VM creation | Packer | Install Ubuntu 24.04 and create each VM |
| ESXi and guest lifecycle | Ansible | Validate ESXi, manage power, bootstrap SSH, configure networking, and safely delete VMs |
| Kubernetes | Kubespray through Ansible | Generate inventory, install dependencies, deploy/reset the cluster, and configure MetalLB |
| Node preparation | Ansible | Apply Kubernetes prerequisites, NIC-offload policy, and Longhorn dependencies |
| Storage reference | Helm manifests | Supply reviewed Longhorn values and a smoke test |
| GitOps bootstrap | Ansible using the external GitOps repository | Install the pinned Argo CD v3 release and create the root Application |
| Applications | External GitOps repository | Reconcile Argo CD runtime configuration and workloads |

## Features

- Multi-host ESXi inventory and certificate-validation controls.
- Repeatable Ubuntu builds from per-VM Packer variables.
- Managed SSH keys, known-host enrollment, guest discovery, and recovery.
- Static networking with the correct interface per node class.
- Persistent NIC-offload configuration for Kubernetes interfaces.
- Generated Kubespray inventory and a pinned Kubespray release.
- Three-control-plane topology with kube-vip and MetalLB.
- Kubernetes health validation and guarded reset.
- Longhorn node preparation and production Helm values.
- Confirmation gates for destructive operations.
- CI with Packer validation, YAML lint, Ansible lint, and playbook syntax checks.

## Current topology

| Role | Hosts | Guest interface |
|---|---|---|
| Ansible control node | `localhost` | Not applicable |
| Kubernetes control plane | `ubuntu_24.04-mgmt-01` through `03` | `ens192` |
| Kubernetes workers / Longhorn | `ubuntu_24.04-wrk-01` through `03` | `ens33` |

VM lifecycle ownership is host-scoped: ESXi 6.7 owns the three `mgmt` VMs, and ESXi 8 owns the three `wrk` VMs. The authoritative mapping is `managed_vm_esxi_ownership` in `inventories/production/group_vars/all.yml`; both hosts belong to `managed_vm_esxi`.

The tracked Packer examples define these VM resources (existing VMs are not resized):

| ESXi target | VM | vCPUs | RAM (MB) | OS disk (MB) | Data disk (MB) |
|---|---|---:|---:|---|---|
| esxi-6.7 | mgmt-01, mgmt-02, mgmt-03 | 6 each | 6144 each | 51200, thin | None |
| esxi-8 | wrk-01 | 8 | 12288 | 204800, thin | 512000, thick |
| esxi-8 | wrk-02, wrk-03 | 6 each | 12288 each | 204800, thin | 512000, thick |

Worker data disks are created unformatted. Ubuntu installs on the first PVSCSI
disk (`/dev/sda`); Longhorn disk preparation is a separate Ansible workflow.
Copy the sizing and disk settings into existing local `.pkrvars.hcl` files before
building: `just secrets-init` preserves existing files. See the
[disk configuration reference](docs/feature-maintenance.md#3-ubuntu-vm-creation-with-packer).

The cluster uses kube-vip for the API virtual IP, MetalLB for service addresses, Calico VXLAN, and IPVS. Authoritative values are under `inventories/production/`; review them before using this repository elsewhere.

## Repository layout

```text
inventories/production/   Hosts and environment variables
playbooks/                Operator entry points
roles/                    Reusable Ansible implementation
packer/                   Ubuntu VM build definition and examples
.generated/kubespray/     Rendered inventory, logs, binaries, and kubeconfig (ignored)
helm/longhorn/            Longhorn namespace, values, and smoke test
docs/                     Focused operational documentation
```

## Maintenance documentation

- [Documentation index](docs/README.md) — map from operator workflows to feature ownership and detailed procedures.
- [Ansible architecture and workflow](docs/ansible-architecture-and-workflow.md) — advanced execution model, inventory/variable resolution, safety contracts, module policy, and official references.
- [Feature maintenance guide](docs/feature-maintenance.md) — ownership, variables, update procedure, validation, and risks for every supported feature.
- [kube-vip per-node interface guide](docs/kube-vip-per-node-interface.md) — control-plane interface, reconciliation, verification, and rollback.

## Prerequisites

Run commands from the repository root. The control machine needs Python 3 with
`venv` (Python 3.12 or newer for Ansible), Ansible, Packer 1.16.1, Git, and access to ESXi and the guest subnet.
The standalone ESXi workflow pins the vSphere plugin to 1.2.7. Post-deployment
work also needs `kubectl` and Helm.

Examples assume the operator uses `~/.ssh/esxi_ansible_ed25519` and its matching `.pub` file.

Run Ansible as the regular operator account, not through `sudo`. Ansible Galaxy
collections are installed per user; running `sudo ansible-playbook` selects a
separate collection tree under `/root/.ansible` and can load stale dependencies.
Use Ansible `become` support, which the playbooks configure where privilege is
required on managed hosts.

## First-time setup

Supporting guides: [inventory and secrets](docs/feature-maintenance.md#1-inventory-and-secrets) and [control-node dependencies](docs/feature-maintenance.md#2-control-node-dependencies).

### Shortcuts with `just` (Ubuntu 24.04 control node)

Install the command runner and Python bootstrap tools, then clone the project:

```bash
sudo apt update
sudo apt install -y just git python3-venv
git clone <repository-url> esxi-ansible-iac
cd esxi-ansible-iac
just                         # List commands; performs no setup or deployment
just bootstrap               # Install system Python 3.12 and venv using sudo
just deps                    # Create .venv/vmware, install Packer, Python tools and collections
just secrets-init            # Copy inventory and Packer examples; preserve existing files
just vaultpass               # Hidden password prompt with confirmation; creates mode 0600
```

`just deps` defaults to `python3.12`; select another compatible interpreter with
`just deps /path/to/python3.12`. The pinned Ansible dependencies require Python
3.12 or newer even though the standalone Packer installer supports Python 3.10.
`just bootstrap` supports Ubuntu 22.04 and 24.04. On 22.04 it adds the
third-party [Deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa);
on 24.04 it uses Ubuntu packages. It installs Python alongside the system Python
without changing `/usr/bin/python3`. Run this explicit system setup once before
`just deps`; dependency installation does not automatically add APT repositories.
If `just` is already available on a 22.04 control node, the same bootstrap applies.
Alternatively, install your selected Python interpreter and its `venv` support
through your organization's package-management process.
If `.venv/vmware` was created with Python 3.10, preserve it before rerunning:

```bash
python3.12 --version
mv .venv/vmware ".venv/vmware-backup-$(date +%Y%m%d-%H%M%S)"
just deps
```

Edit the copied inventory secrets and Packer variables before continuing.
Replace the SSH public-key placeholder, or set `guest_additional_authorized_keys: []`
if only the default automation key is needed. Remove local per-VM Packer variable
files for VMs you do not intend to build, including copied test VM examples.
When using existing encrypted vaults, enter their existing Vault password.
Existing `.vaultpass` files are preserved. Store a recoverable copy of the password
in your password manager.

```bash
just secrets-encrypt         # Encrypt inventory vaults and SSH keys; skip encrypted files
just control-node --ask-become-pass  # Install system dependencies and VMware SDKs
just syntax                  # Local site syntax check
just validate                # Inventory graph, live ESXi validation, site syntax check
```

The recipes use `.venv/vmware/bin/` directly; no virtual-environment activation is
needed. Run `just` as your regular operator account. The dependency recipe installs checksum-verified
Packer 1.16.1 in `.venv/vmware/bin/`; all recipes include that directory on PATH.
For an existing checkout missing Packer, run `just packer-install`. `secrets-init` creates files with mode
0600 and never overwrites existing files. Packer variable files remain local,
Git-ignored HCL files; `secrets-encrypt` only encrypts the inventory files.

After reviewing the local Packer variables:

```bash
just packer-validate esxi-6.7
just packer-validate esxi-8
just packer-build esxi-6.7     # Creates the VMs selected by local variable files
just packer-build esxi-8

# Build only one VM, or start a batch at a selected VM:
just packer-build esxi-8 packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
just packer-build esxi-8 --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-02.pkrvars.hcl
```

Both Packer recipes require an explicit ESXi target and use the existing build
wrapper. Validation does not create VMs. The commands below remain available for
manual setup without `just`.

### 1. Install dependencies

```bash
git clone <repository-url> esxi-ansible-iac
cd esxi-ansible-iac
python3 -m venv .venv/vmware
source .venv/vmware/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml
python3 scripts/install-packer.py
ansible-playbook playbooks/00-control-node.yml
```

### 2. Create local secrets

```bash
cp inventories/production/group_vars/managed_vms/vault.yml.example \
  inventories/production/group_vars/managed_vms/vault.yml
cp inventories/production/group_vars/managed_vms/ssh_keys.yml.example \
  inventories/production/group_vars/managed_vms/ssh_keys.yml
cp inventories/production/host_vars/localhost/vault.yml.example \
  inventories/production/host_vars/localhost/vault.yml
cp inventories/production/host_vars/vm_esxi_8.0/vault.yml.example \
  inventories/production/host_vars/vm_esxi_8.0/vault.yml
cp inventories/production/host_vars/vm_esxi_6.7/vault.yml.example \
  inventories/production/host_vars/vm_esxi_6.7/vault.yml
```

Replace placeholders, create `.vaultpass`, and encrypt secret files:

```bash
ansible-vault encrypt inventories/production/group_vars/managed_vms/vault.yml
ansible-vault encrypt inventories/production/group_vars/managed_vms/ssh_keys.yml
ansible-vault encrypt inventories/production/host_vars/localhost/vault.yml
ansible-vault encrypt inventories/production/host_vars/vm_esxi_8.0/vault.yml
ansible-vault encrypt inventories/production/host_vars/vm_esxi_6.7/vault.yml
git status --short
```

Keep ESXi credentials, Vault passwords, SSH private keys, and local Packer variables outside Git.

### 3. Validate

```bash
ansible-inventory --graph
ansible-playbook playbooks/00-validate.yml
ansible-playbook playbooks/99-site-run.yml --syntax-check
```

`ansible.cfg` selects the production inventory by default. Use `-i` for another environment.

## Build Ubuntu VMs

Maintenance reference: [Ubuntu VM creation with Packer](docs/feature-maintenance.md#3-ubuntu-vm-creation-with-packer).

Packer owns VM creation. Create separate ignored common variable files for each ESXi host:

```bash
cp packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl.example \
  packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl
cp packer/ubuntu-24.04/esxi-8.pkrvars.hcl.example \
  packer/ubuntu-24.04/esxi-8.pkrvars.hcl

for directory in esxi-6.7 esxi-8; do
  for file in packer/ubuntu-24.04/vms/"$directory"/*.pkrvars.hcl.example; do
    cp "$file" "${file%.example}"
  done
done
```

Build the control-plane VMs on ESXi 6.7 and workers on ESXi 8:

```bash
packer/build-ubuntu-vms.sh --target esxi-6.7
packer/build-ubuntu-vms.sh --target esxi-8
```

Validate without creating a VM, build one selected VM, or start a multi-VM
batch at a selected variable file:

```bash
packer/build-ubuntu-vms.sh --target esxi-6.7 --validate-only

packer/build-ubuntu-vms.sh \
  --target esxi-8 \
  packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl

packer/build-ubuntu-vms.sh \
  --target esxi-8 \
  --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
```

`--start-at` filters the ordered variable-file list; it does not resume the
internal state of an interrupted Packer build. A partially created VM may
still require inspection or cleanup before rebuilding it.

The required target prevents mixing one ESXi host's common variables with the
other host's VM definitions. Local `*.pkrvars.hcl` files may contain credentials
and are ignored. Commit only sanitized `.example` files. ESXi 6.7 uses the
qualified `20s` boot wait and `1500ms` key-group interval from its common file.

## Reconcile guests

Supporting guides: [guest access](docs/feature-maintenance.md#5-guest-ssh-discovery-bootstrap-and-rotation) and [networking/NIC offloads](docs/feature-maintenance.md#6-guest-networking-and-nic-offloads).

```bash
ansible-playbook playbooks/03-vm-validate-managed.yml
ansible-playbook playbooks/04-vm-power.yml \
  -e scope=all -e vm_power_state=powered-on
ansible-playbook playbooks/99-guest-site.yml
```

### VM deletion shortcut

`just vm-delete VM CONFIRMATION` calls the existing deletion playbook. Repeat the
exact managed VM name as confirmation; a missing or different name blocks execution.

```bash
# Preview through Ansible check mode (requires ESXi connectivity):
just vm-delete ubuntu_24.04-wrk-01 ubuntu_24.04-wrk-01 --check

# Delete the VM and its associated disks:
just vm-delete ubuntu_24.04-wrk-01 ubuntu_24.04-wrk-01
```

The command is restricted to one managed VM. Existing ownership, unique-name,
placement, optional UUID confirmation, and force settings remain in Ansible.
Force deletion defaults to false. `--limit` refers to the owning ESXi inventory
host, not the guest name. This does not drain Kubernetes workloads, remove cluster
membership, or edit inventory; complete the appropriate decommissioning first.
Check mode is a preview and cannot guarantee a later deletion will succeed.

### VM power shortcuts

`just` delegates power operations to `04-vm-power.yml`, which validates
`esxi_allowed_power_states` from inventory and selects each VM's owning ESXi host.

```bash
just vm-power-states
just vm-power ubuntu_24.04-mgmt-01 powered-on
just vm-power ubuntu_24.04-mgmt-01 shutdown-guest
just vm-power ubuntu_24.04-wrk-01 reboot-guest

# Explicit bulk operation, restricted to VMs owned by ESXi 6.7:
just vm-power-all powered-on --limit vm_esxi_6.7
```

Configured states are `powered-on`, `powered-off`, `shutdown-guest`,
`reboot-guest`, `restarted`, and `suspended`. The inventory remains the authority;
the recipes do not maintain a separate allowed-state list. These commands apply
power operations immediately. `vm-power-all` without `--limit` targets all managed
VMs across both ESXi hosts. VM names must belong to the managed inventory; adding
a Packer variable file alone does not register a VM for power management.
Use the single-VM command for targeted maintenance; these wrappers do not drain
Kubernetes workloads or orchestrate rolling restarts.

Preview supported changes with `--check`. If key validation fails, verify the public key:

```bash
ssh-keygen -y -f ~/.ssh/esxi_ansible_ed25519 > /tmp/esxi_ansible_ed25519.pub
diff -u /tmp/esxi_ansible_ed25519.pub ~/.ssh/esxi_ansible_ed25519.pub
```

Use `17-ssh-key-rotate.yml` for an intentional rotation.

## Deploy Kubernetes

Supporting guides: [Kubespray lifecycle](docs/feature-maintenance.md#7-kubernetes-inventory-and-kubespray-lifecycle), [kube-vip](docs/kube-vip-per-node-interface.md), [MetalLB/add-ons](docs/feature-maintenance.md#9-metallb-and-cluster-add-ons), and [cluster health](docs/feature-maintenance.md#10-kubernetes-health-and-operator-kubeconfig).

```bash
ansible-playbook playbooks/07-kubespray-inventory.yml
ansible-playbook playbooks/08-kubespray-install.yml
ansible-playbook playbooks/10-kubernetes-node-prepare.yml
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true
ansible-playbook playbooks/13-kubespray-metallb.yml
ansible-playbook playbooks/14-kubernetes-health.yml
```

The enable flag prevents accidental deployment. Generated Kubespray inventory is derived data; change `inventories/production/` and regenerate it.

For the complete workflow after VMs and credentials are ready:

```bash
ansible-playbook playbooks/99-kubernetes-site.yml \
  -e kubespray_control_enable_cluster_deploy=true
```

See [per-node kube-vip interface handling](docs/kube-vip-per-node-interface.md) for the mixed-interface design.

## Prepare Longhorn nodes

Maintenance reference: [Longhorn node preparation](docs/feature-maintenance.md#11-longhorn-node-preparation).

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml
```

Longhorn workloads and application volumes should normally be reconciled by the GitOps repository. Avoid creating a second source of truth here.

## Bootstrap Argo CD v3

Maintenance reference: [automated Argo CD v3 bootstrap](docs/feature-maintenance.md#12-automated-argo-cd-v3-bootstrap).

Kubespray's bundled Argo CD add-on remains disabled because Kubespray v2.31.0
pins Argo CD v2.14.5. This project instead performs an idempotent post-cluster
bootstrap from the manifests owned by `/opt/gitops-platform`, then hands
continuous ownership to the `argocd-runtime` Application.

After the base cluster is healthy and `/opt/gitops-platform` is present:

```bash
ansible-playbook playbooks/19-argocd-bootstrap.yml \
  -e argocd_bootstrap_enable=true
```

For a complete VM, Kubernetes, add-on, health, and GitOps bootstrap workflow:

```bash
ansible-playbook playbooks/99-platform-site.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e argocd_bootstrap_enable=true
```

Both flags are deliberate safety gates. The bootstrap validates API and node
health, server-side validates the pinned manifests, applies Argo CD, waits for
its workloads, applies AppProjects and `root-applications`, and verifies the
expected Argo CD version. It does not initialize Vault or expose secret values.

## Canonical playbooks

| Range | Purpose |
|---|---|
| `00`–`05` | Prepare/validate the controller and manage ESXi VMs |
| `06`, `11`, `12`, `17` | Bootstrap, network, recover, and rotate guest access |
| `07`–`10`, `13`–`15` | Generate, deploy, validate, and reset Kubernetes |
| `16-longhorn-node-prepare.yml` | Install Longhorn node prerequisites |
| `18-project-sync.yml` | Synchronize project content |
| `19-argocd-bootstrap.yml` | Guarded Argo CD v3 bootstrap from `gitops-platform` |
| `99-esxi-site.yml` | Validate ESXi, gather facts, and power on all managed VMs |
| `99-guest-discover.yml` | Discover and verify guests |
| `99-guest-site.yml` | Reconcile managed guests |
| `99-kubernetes-site.yml` | Prepare the controller and nodes, then run the guarded base-cluster deployment |
| `99-platform-site.yml` | Deploy the cluster, add-ons, health gates, and Argo CD v3 |
| `99-site-run.yml` | Run the normal ESXi/guest workflow |

`99-site-run.yml` composes `99-esxi-site.yml` and `99-guest-site.yml`, powering on every managed VM before guest reconciliation. Use `04-vm-power.yml -e vm_power_name=<name>` for a single-VM power operation.

`99-kubernetes-site.yml` renders the Kubespray inventory through
`09-kubespray-deploy.yml`, but it does not apply the post-deployment MetalLB
address pools or run the final health playbook. When using that base workflow,
run `13-kubespray-metallb.yml` and `14-kubernetes-health.yml` afterward.
`99-platform-site.yml` already composes both steps; do not run them again merely
because the full platform workflow completed successfully.

`99-platform-site.yml` composes those post-deployment steps and the guarded
GitOps bootstrap. It requires both deployment enable flags and keeps the
Kubespray Argo CD add-on disabled to prevent competing field ownership.

Unnumbered playbooks such as `site-esxi.yml`, `site-guest.yml`, `rotate-ssh-key.yml`, and `sync-project.yml` are compatibility wrappers. Prefer numbered entry points for new automation.

## Safety

Maintenance reference: [change checklist](docs/feature-maintenance.md#change-checklist).

- Run `--check` where supported and use `--limit` for partial maintenance.
- Inspect confirmation variables before VM deletion or Kubespray reset.
- Back up data and confirm Longhorn replica health before maintenance.
- Never disable TLS validation merely to hide an unknown certificate.
- Do not edit generated Kubespray inventory as durable configuration.

Example guarded deletion:

```bash
ansible-playbook playbooks/05-vm-delete.yml \
  -e vm_delete_name=ubuntu_24.04-wrk-01 \
  -e vm_delete_confirm=true \
  -e vm_delete_confirm_name=ubuntu_24.04-wrk-01
```

## Troubleshooting

Supporting guide: [Kubernetes health and operator kubeconfig](docs/feature-maintenance.md#10-kubernetes-health-and-operator-kubeconfig).

```bash
# Inventory and variables
ansible-inventory --graph
ansible-inventory --host ubuntu_24.04-mgmt-01
ansible managed_vm_esxi -m ansible.builtin.debug \
  -a 'var=esxi_managed_vm_names'
ansible-playbook playbooks/00-validate.yml -vv

# SSH
ansible managed_vms -m ansible.builtin.ping

# Kubernetes
ansible-playbook playbooks/14-kubernetes-health.yml
kubectl get nodes -o wide
kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
```

Derived variables can remain as literal Jinja expressions in
`ansible-inventory --host` output. Use `ansible.builtin.debug` as shown above
to evaluate `esxi_managed_vm_names` separately for each ESXi host. See
[ESXi ownership and target inspection](docs/feature-maintenance.md#inspect-ownership-and-power-targets)
for the key definitions and safe `04-vm-power.yml` previews.

Treat failed probes as symptoms: inspect pod events, logs, resources, and dependencies before restarting or redeploying.

## Development and CI

Maintenance reference: [CI and repository quality](docs/feature-maintenance.md#14-ci-and-repository-quality).

```bash
scripts/validate-packer.sh
python3 scripts/check-markdown-links.py
pre-commit run --all-files
git diff --check
git diff --stat
git status --short
```

When extending the project:

1. Put environment data in inventory, not role tasks.
2. Put reusable behavior in roles and keep playbooks thin.
3. Require explicit opt-in for destructive or cluster-wide actions.
4. Keep stable workflows here and detailed procedures under `docs/`.
5. Extend canonical implementations instead of duplicating wrappers.

## Design boundaries

- This repository supports the committed topology; it is not a generic ESXi framework.
- Packer creates VMs; Ansible manages them after creation.
- Kubespray owns Kubernetes installation; this project supplies inputs and orchestration.
- Ansible performs the repeatable Argo CD bootstrap from the GitOps source;
  the GitOps platform owns Argo CD and in-cluster applications afterward.
- Longhorn capacity, placement, and data protection require ongoing monitoring.
