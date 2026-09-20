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
| Applications | External GitOps repository | Reconcile Argo CD applications and workloads |

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
- CI with YAML lint, Ansible lint, and playbook syntax checks.

## Current topology

| Role | Hosts | Guest interface |
|---|---|---|
| Ansible control node | `localhost` | Not applicable |
| Kubernetes control plane | `ubuntu_24.04-mgmt-01` through `03` | `ens192` |
| Kubernetes workers / Longhorn | `ubuntu_24.04-wrk-01` through `03` | `ens33` |

VM lifecycle ownership is host-scoped: ESXi 6.7 owns the three `mgmt` VMs, and ESXi 8 owns the three `wrk` VMs. The authoritative mapping is `managed_vm_esxi_ownership` in `inventories/production/group_vars/all.yml`; both hosts belong to `managed_vm_esxi`.

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
- [Feature maintenance guide](docs/feature-maintenance.md) — ownership, variables, update procedure, validation, and risks for every supported feature.
- [kube-vip per-node interface guide](docs/kube-vip-per-node-interface.md) — control-plane interface, reconciliation, verification, and rollback.

## Prerequisites

Run commands from the repository root. The control machine needs Python 3 with `venv`, Ansible, Packer, Git, and access to ESXi and the guest subnet. Post-deployment work also needs `kubectl` and Helm.

Examples assume the operator uses `~/.ssh/esxi_ansible_ed25519` and its matching `.pub` file.

Run Ansible as the regular operator account, not through `sudo`. Ansible Galaxy
collections are installed per user; running `sudo ansible-playbook` selects a
separate collection tree under `/root/.ansible` and can load stale dependencies.
Use Ansible `become` support, which the playbooks configure where privilege is
required on managed hosts.

## First-time setup

Supporting guides: [inventory and secrets](docs/feature-maintenance.md#1-inventory-and-secrets) and [control-node dependencies](docs/feature-maintenance.md#2-control-node-dependencies).

### 1. Install dependencies

```bash
git clone <repository-url> esxi-ansible-iac
cd esxi-ansible-iac
python3 -m venv .venv/vmware
source .venv/vmware/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml
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
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-6.7

packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --vm-var-dir packer/ubuntu-24.04/vms/esxi-8
```

Build or resume one VM by passing its file explicitly with the matching common host file:

```bash
packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl \
  packer/ubuntu-24.04/vms/esxi-6.7/mgmt-01.pkrvars.hcl

packer/build-ubuntu-vms.sh \
  --common-var-file packer/ubuntu-24.04/esxi-8.pkrvars.hcl \
  --start-at packer/ubuntu-24.04/vms/esxi-8/wrk-01.pkrvars.hcl
```

Local `*.pkrvars.hcl` files may contain credentials and are ignored. Commit only sanitized `.example` files.

## Reconcile guests

Supporting guides: [guest access](docs/feature-maintenance.md#5-guest-ssh-discovery-bootstrap-and-rotation) and [networking/NIC offloads](docs/feature-maintenance.md#6-guest-networking-and-nic-offloads).

```bash
ansible-playbook playbooks/03-vm-validate-managed.yml
ansible-playbook playbooks/04-vm-power.yml \
  -e scope=all -e vm_power_state=powered-on
ansible-playbook playbooks/99-guest-site.yml
```

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

## Canonical playbooks

| Range | Purpose |
|---|---|
| `00`–`05` | Prepare/validate the controller and manage ESXi VMs |
| `06`, `11`, `12`, `17` | Bootstrap, network, recover, and rotate guest access |
| `07`–`10`, `13`–`15` | Generate, deploy, validate, and reset Kubernetes |
| `16-longhorn-node-prepare.yml` | Install Longhorn node prerequisites |
| `18-project-sync.yml` | Synchronize project content |
| `99-esxi-site.yml` | Validate ESXi, gather facts, and power on all managed VMs |
| `99-guest-discover.yml` | Discover and verify guests |
| `99-guest-site.yml` | Reconcile managed guests |
| `99-kubernetes-site.yml` | Prepare the controller and nodes, then run the guarded base-cluster deployment |
| `99-site-run.yml` | Run the normal ESXi/guest workflow |

`99-site-run.yml` composes `99-esxi-site.yml` and `99-guest-site.yml`, powering on every managed VM before guest reconciliation. Use `04-vm-power.yml -e vm_power_name=<name>` for a single-VM power operation.

`99-kubernetes-site.yml` renders the Kubespray inventory through
`09-kubespray-deploy.yml`, but it does not apply the post-deployment MetalLB
address pools or run the final health playbook. Run `13-kubespray-metallb.yml`
and `14-kubernetes-health.yml` afterward when those checks are required.

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
ansible-playbook playbooks/00-validate.yml -vv

# SSH
ansible managed_vms -m ansible.builtin.ping

# Kubernetes
ansible-playbook playbooks/14-kubernetes-health.yml
kubectl get nodes -o wide
kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
```

Treat failed probes as symptoms: inspect pod events, logs, resources, and dependencies before restarting or redeploying.

## Development and CI

Maintenance reference: [CI and repository quality](docs/feature-maintenance.md#13-ci-and-repository-quality).

```bash
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
- The GitOps platform owns in-cluster applications after bootstrap.
- Longhorn capacity, placement, and data protection require ongoing monitoring.
