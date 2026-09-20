# Feature Maintenance Guide

[Documentation index](README.md) · [Project README](../README.md) · [kube-vip procedure](kube-vip-per-node-interface.md)

## Purpose

This document maps every supported project feature to its source-of-truth files, entry playbooks, important controls, validation, and maintenance risks.

Use it when changing infrastructure configuration. The root README explains how to operate the platform; this guide explains where and how to maintain each capability.

## Maintenance rules

Apply these rules to every change:

1. Change source files, never generated output under `.generated/`.
2. Keep environment-specific values in `inventories/production/`.
3. Keep reusable behavior in roles and playbooks as thin entry points.
4. Put secrets only in ignored, encrypted Vault files or protected environment variables.
5. Preview supported changes with `--check` and limit risky maintenance to one node.
6. Require an explicit enable flag or confirmation for destructive actions.
7. Run the feature-specific checks, followed by the full pre-commit suite.
8. Update this guide when ownership, variables, or operator workflows change.

## Feature ownership matrix

| Feature | Primary entry point | Main source of truth |
|---|---|---|
| Inventory and secrets | `00-validate.yml` | `inventories/production/` |
| Control-node dependencies | `00-control-node.yml` | `roles/control_node_prerequisites/` |
| Ubuntu VM creation | `packer/build-ubuntu-vms.sh` | `packer/ubuntu-24.04/` |
| ESXi facts and VM lifecycle | `01`–`05`, `99-esxi-site.yml` | ESXi roles and host variables |
| Guest SSH and bootstrap | `06`, `12`, `17`, `99-guest-site.yml` | Guest authentication roles and managed VM variables |
| Guest networking and offloads | `11-guest-network.yml` | Inventory host variables and guest roles |
| Kubernetes inventory/deployment | `07`–`10`, `99-kubernetes-site.yml` | Kubespray roles and `group_vars/all.yml` |
| kube-vip API endpoint | `07`, `09`, `14` | Per-host interface plus shared VIP variables |
| MetalLB | `13-kubespray-metallb.yml` | Kubespray and MetalLB role variables |
| Cluster health and kubeconfig | `14-kubernetes-health.yml` | Health and kubeconfig roles |
| Longhorn node preparation | `16-longhorn-node-prepare.yml` | Longhorn inventory and role |
| Project synchronization | `18-project-sync.yml` | Synchronization playbook |
| CI and quality controls | GitHub Actions / pre-commit | `.github/workflows/validate.yml` and `.pre-commit-config.yaml` |

## 1. Inventory and secrets

### Purpose

Defines ESXi endpoints, managed guests, Kubernetes topology, node addresses, interface names, Longhorn membership, and environment-wide settings.

### Owned files

- `inventories/production/hosts.yml`
- `inventories/production/group_vars/all.yml`
- `inventories/production/group_vars/vmware_esxi.yml`
- `inventories/production/group_vars/managed_vms/main.yml`
- `inventories/production/group_vars/longhorn_nodes.yml`
- `inventories/production/host_vars/*/main.yml`
- Sanitized `vault.yml.example` and `ssh_keys.yml.example` files

Real `vault.yml`, `ssh_keys.yml`, and `.vaultpass` files are local secrets and ignored by Git.

### Maintenance procedure

- Add a VM to the appropriate inventory groups.
- Define `ansible_host` and `kubernetes_primary_interface` for every Kubernetes node.
- Add host-specific placement or storage settings under `host_vars`.
- Assign each managed VM exactly once in `managed_vm_esxi_ownership`; use the `managed_vm_esxi` group for lifecycle hosts.
- Add shared platform settings to `group_vars/all.yml` only when they genuinely apply to the whole environment.
- Update a sanitized example whenever a required secret key changes.

### Validate

```bash
ansible-inventory --graph
ansible-inventory --host ubuntu_24.04-mgmt-01
ansible-playbook playbooks/00-validate.yml
```

### Cautions

Changing an inventory alias changes Ansible identity and generated Kubernetes node naming. Changing `ansible_host` or a primary interface can interrupt SSH or cluster networking. Treat both as migrations.

## 2. Control-node dependencies

### Purpose

Provides the local Python virtual environment and VMware SDK dependencies used by Ansible.

### Owned files

- `playbooks/00-control-node.yml`
- `roles/control_node_prerequisites/`
- `requirements.yml`
- `requirements-dev.txt`
- `ansible.cfg`

### Important controls

- `control_node_prerequisites_vmware_venv_dir`
- `control_node_prerequisites_python_apt_packages`
- `control_node_prerequisites_vmware_python_packages`

### Maintain and validate

Update package lists in role defaults, not directly in tasks. After changing dependencies:

```bash
ansible-playbook playbooks/00-control-node.yml --check
ansible-playbook playbooks/00-control-node.yml
.venv/vmware/bin/python -c 'import pyVim, pyVmomi'
ansible-inventory --graph
```

Run these commands as the regular operator account without `sudo`. The project
expects user-scoped Ansible collections under `~/.ansible/collections`; using
`sudo ansible-playbook` switches to root's independent collection tree. Managed
host privilege escalation belongs in playbook `become` settings.

Pin validation tools in `requirements-dev.txt` so local and GitHub Actions behavior remains reproducible.

## 3. Ubuntu VM creation with Packer

### Purpose

Creates Ubuntu 24.04 VMs and performs the initial unattended installation. Ansible does not create VMs.

### Owned files

- `packer/ubuntu-24.04/ubuntu-24.04.pkr.hcl`
- `packer/ubuntu-24.04/http/`
- `packer/ubuntu-24.04/*.pkrvars.hcl.example`
- `packer/ubuntu-24.04/vms/esxi-8/`
- `packer/ubuntu-24.04/vms/esxi-6.7/`
- `packer/build-ubuntu-vms.sh`

### Maintenance procedure

- Put shared ESXi/build settings in a local common variable file.
- Put VM-specific CPU, memory, disk, datastore, and name settings in per-VM files.
- Keep real `*.pkrvars.hcl` files untracked.
- Update sanitized examples whenever required variables change.
- Always pass the matching common variable file and VM directory together:
  `esxi-6.7` for management VMs and `esxi-8` for worker VMs.

### Validate

```bash
packer init packer/ubuntu-24.04
packer fmt -check -recursive packer/ubuntu-24.04
packer validate \
  -var-file=packer/ubuntu-24.04/esxi-6.7.pkrvars.hcl \
  -var-file=packer/ubuntu-24.04/vms/esxi-6.7/mgmt-01.pkrvars.hcl \
  packer/ubuntu-24.04
```

A Packer build creates or replaces infrastructure. Validation is safe; building requires a separate operator decision.

## 4. ESXi validation and VM lifecycle

### Purpose

Validates ESXi credentials and placement, gathers facts, lists VMs, verifies managed VM names, manages power, and performs guarded deletion.

### Owned files

- `roles/esxi_validate/`
- `roles/esxi_facts/`
- `roles/vm_power/`
- `roles/vm_delete/`
- `playbooks/00-validate.yml` through `05-vm-delete.yml`
- `playbooks/99-esxi-site.yml`

### Important controls

- `esxi_hostname`, `esxi_username`, `esxi_password`
- `esxi_validate_certs`
- `esxi_datacenter`, `esxi_default_folder`
- `managed_vm_names`
- `vm_power_state`
- `vm_delete_confirm`, `vm_delete_confirm_name`
- Optional UUID and delete-all confirmations

### Validate

```bash
ansible-playbook playbooks/00-validate.yml
ansible-playbook playbooks/01-esxi-facts.yml
ansible-playbook playbooks/03-vm-validate-managed.yml
```

Power, validation, discovery, recovery, and deletion target `managed_vm_esxi`. The `managed_vm_esxi_ownership` map routes each VM only to its owning ESXi host and must assign every `managed_vms` member exactly once.

Never weaken deletion confirmations to simplify automation.

## 5. Guest SSH, discovery, bootstrap, and rotation

### Purpose

Validates the managed SSH key pair, enrolls host keys, waits for SSH, bootstraps packages/services, discovers guest addresses through VMware Tools, recovers access, and rotates keys safely.

### Owned files

- `roles/guest_auth_validate/`
- `roles/ssh_known_hosts/`
- `roles/vm_wait/`
- `roles/guest_base/`
- `roles/guest_ssh_recovery/`
- `playbooks/06-guest-bootstrap.yml`
- `playbooks/12-guest-ssh-recover.yml`
- `playbooks/17-ssh-key-rotate.yml`
- `playbooks/99-guest-discover.yml`
- `playbooks/99-guest-site.yml`

### Important controls

- `ansible_user`, `ansible_ssh_private_key_file`
- Managed public key variables in `ssh_keys.yml`
- `guest_base_packages`, `guest_base_services`
- `guest_base_enable_password_ssh_disabled`
- `ssh_known_hosts_enable_remove_old`
- `guest_ssh_recovery_enable_recovery`
- `guest_ssh_recovery_vm_names`
- `rotation_phase` for key rotation

### Maintain and validate

```bash
ansible-playbook playbooks/99-guest-site.yml --check --limit <inventory-host>
ansible <inventory-host> -m ansible.builtin.ping
```

Check mode previews timezone and NTP changes but skips the clock-synchronization
wait because it cannot enable NTP. A normal reconciliation still waits for and
requires `NTPSynchronized=yes`.

Recovery is disabled by default and must name explicit VMs. Key rotation has deploy and revoke phases; verify access with the new key before revoking the old one.

## 6. Guest networking and NIC offloads

### Purpose

Maintains static Netplan configuration and persistent NIC-offload policy for Kubernetes traffic.

### Owned files

- `inventories/production/hosts.yml`
- `inventories/production/group_vars/managed_vms/main.yml`
- `inventories/production/group_vars/all.yml`
- `roles/guest_network/`
- `roles/guest_base/`
- `playbooks/11-guest-network.yml`
- `playbooks/99-guest-site.yml`

### Important controls

- `ansible_host`
- `kubernetes_primary_interface`
- Guest address, gateway, DNS, and search-domain variables
- `guest_base_enable_nic_offloads_disabled`
- `guest_base_nic_offload_interface`
- `guest_base_nic_offload_features`

### Safe update procedure

1. Confirm the live link, address, route, and DNS.
2. Update one inventory host.
3. Run check mode with `--limit`.
4. Apply one node at a time; networking uses serial execution.
5. Reconnect and run Kubernetes health checks before moving on.

```bash
ansible-playbook playbooks/11-guest-network.yml \
  --check --limit <inventory-host>
ansible-playbook playbooks/11-guest-network.yml \
  --limit <inventory-host>
ansible-playbook playbooks/14-kubernetes-health.yml
```

See [kube-vip per-node interface configuration](kube-vip-per-node-interface.md) before changing a control-plane interface.

## 7. Kubernetes inventory and Kubespray lifecycle

### Purpose

Renders Kubespray inputs, installs the pinned Kubespray version, prepares nodes, deploys or resets Kubernetes, and installs the operator kubeconfig.

### Owned files

- `roles/kubespray_inventory/`
- `roles/kubespray_control/`
- `roles/kubernetes_node_prepare/`
- `roles/control_plane_kubeconfig/`
- `playbooks/07-kubespray-inventory.yml` through `10-kubernetes-node-prepare.yml`
- `playbooks/15-kubespray-reset.yml`
- `playbooks/99-kubernetes-site.yml`
- Kubernetes variables in `inventories/production/group_vars/all.yml`

### Important controls

- `kubespray_version`
- Control-plane, etcd, and worker inventory groups
- Pod and service CIDRs
- Calico backend and encapsulation
- Container manager and kube-proxy mode
- DNS and NodeLocal DNS
- `kubespray_control_enable_cluster_deploy`
- `kubespray_control_enable_cluster_reset`

### Maintenance procedure

Change durable inputs in production inventory, then render:

```bash
ansible-playbook playbooks/07-kubespray-inventory.yml
git diff --check
```

Generated inventory, logs, fact cache, binaries, and kubeconfig under `.generated/` are runtime artifacts and must not be committed.

Deploy only with the explicit guard:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true
```

`99-kubernetes-site.yml` prepares the controller and nodes and invokes this
guarded base-cluster deployment. It does not run `13-kubespray-metallb.yml` or
`14-kubernetes-health.yml`; apply MetalLB address pools and perform the final
health validation as explicit post-deployment steps.

Kubernetes or Kubespray version upgrades require release-note review, backup validation, supported upgrade-path confirmation, and a separate change window. Reset is destructive and must never be part of normal reconciliation.

## 8. kube-vip control-plane endpoint

### Purpose

Provides the highly available Kubernetes API endpoint at `172.16.6.150`.

### Ownership

- Per-node interfaces: `inventories/production/hosts.yml`
- Shared VIP settings: `inventories/production/group_vars/all.yml`
- Rendering: `roles/kubespray_inventory/`
- Validation: `roles/kubernetes_health/`

The current control planes use `ens192`; workers use `ens33`. There is no global interface variable.

Use the dedicated [kube-vip per-node interface guide](kube-vip-per-node-interface.md) for change, verification, failover, troubleshooting, and rollback procedures.

## 9. MetalLB and cluster add-ons

### Purpose

Enables Kubespray add-ons and applies MetalLB address pools after its webhook is ready.

### Owned files

- Add-on variables in `inventories/production/group_vars/all.yml`
- `roles/kubespray_inventory/templates/addons.yml.j2`
- `roles/kubespray_metallb/`
- `playbooks/13-kubespray-metallb.yml`

### Important controls

- `kubespray_inventory_enable_metallb`
- `kubespray_inventory_metallb_ip_range`
- Metrics Server, cert-manager, Argo CD, registry, and Helm enable flags
- `kubespray_metallb_controller_timeout`
- `kubespray_metallb_apply_retries`

### Maintain and validate

Confirm that MetalLB ranges are reserved, unused, on the correct L2 network, and outside DHCP, node, and kube-vip addresses.

```bash
ansible-playbook playbooks/13-kubespray-metallb.yml --syntax-check
ansible-playbook playbooks/13-kubespray-metallb.yml
ansible-playbook playbooks/14-kubernetes-health.yml
```

kube-vip owns only the API VIP. MetalLB owns application `LoadBalancer` addresses; do not enable kube-vip service mode.

## 10. Kubernetes health and operator kubeconfig

### Purpose

Installs a usable operator kubeconfig and validates nodes, API readiness, kube-vip, system workloads, metrics, cert-manager, MetalLB, internal CA, NIC offloads, recent warning events, and optional load-balancer behavior.

### Owned files

- `roles/control_plane_kubeconfig/`
- `roles/kubernetes_health/`
- `playbooks/14-kubernetes-health.yml`

### Important controls

- Generated artifacts directory and kubeconfig paths
- Rollout timeout
- Feature-enable variables inherited from Kubespray inventory
- Warning event window, failure policy, and exclusion regex
- kube-vip restart observation and optional lifetime ceiling
- Optional LoadBalancer smoke test

### Maintain and validate

Add a health assertion when introducing a cluster service that operators depend on. Keep checks read-only unless a specifically named smoke test is explicitly enabled.

```bash
ansible-playbook playbooks/14-kubernetes-health.yml
kubectl get nodes -o wide
kubectl get events -A --sort-by=.lastTimestamp
```

A failed health check is diagnostic evidence; it is not permission to restart or redeploy unrelated workloads.

## 11. Longhorn node preparation

### Purpose

Installs iSCSI, NFS, encryption, kernel-module, mount, and optional dedicated-disk prerequisites on the `longhorn_nodes` group.

### Owned files

- `inventories/production/group_vars/longhorn_nodes.yml`
- `inventories/production/host_vars/*/longhorn.yml`
- `roles/longhorn_node_prepare/`
- `playbooks/16-longhorn-node-prepare.yml`
- `helm/longhorn/` reference manifests

### Important controls

- `longhorn_node_prepare_data_path`
- Per-node data device
- Filesystem and mount options
- `longhorn_node_prepare_has_data_disk`
- `longhorn_node_prepare_enable_disk_format`
- Optional multipath disablement

### Safe update procedure

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --check --limit <worker>
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --limit <worker>
```

Disk formatting must remain disabled unless a verified, empty target device is intentionally being initialized. Before node maintenance, confirm Longhorn replica health, free capacity, and data locality. In-cluster Longhorn deployment and volumes remain owned by GitOps.

## 12. Project synchronization

### Purpose

Copies a filtered working-tree snapshot to a managed guest when a normal Git clone or pull is unavailable.

### Owned files

- `playbooks/18-project-sync.yml`
- Compatibility wrapper `playbooks/sync-project.yml`

### Use and validate

```bash
ansible-playbook playbooks/18-project-sync.yml \
  -e target_host=ubuntu_24.04-mgmt-01
```

The target must be a managed inventory host and use a protected private key. Synchronization excludes repository metadata, virtual environments, generated files, credentials, logs, and local Packer variables. Prefer Git for normal source distribution.

## 13. CI and repository quality

### Purpose

Ensures inventory can load and committed YAML/Ansible content remains valid.

### Owned files

- `.github/workflows/validate.yml`
- `.pre-commit-config.yaml`
- `.yamllint.yml`
- `.ansible-lint`
- `requirements-dev.txt`
- `requirements.yml`

### Current checks

- Production inventory graph
- YAML lint
- Ansible lint
- Syntax check for every playbook

### Local validation

```bash
source .venv/vmware/bin/activate
PATH="$PWD/.venv/vmware/bin:$PATH" \
  .venv/vmware/bin/pre-commit run --all-files
git diff --check
git status --short
```

When adding a new file type or generated artifact, update both CI coverage and `.gitignore`. Never solve a lint failure by excluding valid infrastructure code without documenting why.

## Change checklist

Use this checklist for configuration work:

- [ ] Identified the owning feature and source-of-truth file.
- [ ] Confirmed the live state before changing desired state.
- [ ] Checked whether secrets or generated artifacts are involved.
- [ ] Limited the first application to the smallest safe scope.
- [ ] Preserved destructive-action guards.
- [ ] Ran the feature-specific syntax and validation commands.
- [ ] Ran the full pre-commit suite.
- [ ] Reviewed `git diff --check`, `git diff`, and `git status --short`.
- [ ] Updated the root README or feature documentation when the operator contract changed.
- [ ] Prepared a rollback based on source-of-truth changes, not live-only patches.

---

[Documentation index](README.md) · [Project README](../README.md)
