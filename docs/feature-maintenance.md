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
| Argo CD v3 bootstrap | `19-argocd-bootstrap.yml`, `99-platform-site.yml` | `gitops-platform` manifests and `roles/argocd_bootstrap/` |
| Project synchronization | `18-project-sync.yml` | Synchronization playbook |
| CI and quality controls | GitHub Actions / pre-commit | `.github/workflows/validate.yml` and `.pre-commit-config.yaml` |

## First-clone command shortcuts

The root `justfile` wraps existing workflows and supports Ubuntu 24.04's `just`
1.21. `just` lists commands; it does not provision infrastructure. See the
[setup shortcuts](../README.md#shortcuts-with-just-ubuntu-2404-control-node) for the
ordered operator workflow and the [complete recipe reference](just-commands.md)
for mappings and intentionally explicit playbook entry points.

- `just bootstrap` runs `scripts/bootstrap-control-node.sh` using sudo for system
  packages. Ubuntu 22.04 adds the Deadsnakes PPA; 24.04 uses Ubuntu packages.
  Other distributions/releases are rejected before changes. System Python and
  existing project environments are preserved.
- `just deps` installs checksum-verified Packer 1.16.1, creates the Python
  environment with `python3.12`, and installs pinned tools and collections.
  Pass an interpreter with `just deps /path/to/python3.12`. Setup rejects Python
  below 3.12 and preserves incompatible existing environments for manual backup. `just packer-install`
  installs only Packer using `scripts/install-packer.py` (Linux x86_64/aarch64).
  Tools live in `.venv/vmware/bin/`, which recipes prepend to PATH. Update the
  installer checksums alongside the version when qualifying a new Packer release.
- `just secrets-init`, `just vaultpass`, and `just secrets-encrypt` use
  `scripts/local-secrets.py`. New local files are mode 0600; initialization never
  overwrites existing files. Password entry is interactive and hidden.
- `just control-node` invokes the control-node prerequisite playbook after secrets setup.
- `just syntax` checks site syntax. `just validate` lists selected ESXi hosts,
  checks site syntax, then runs `01-esxi-facts.yml` for configuration assertions
  and live host facts. All steps receive the same Ansible arguments, including
  `-i`, `--limit`, and `-e`. Empty host selections or execution-control options
  that skip the facts task do not verify connectivity. `00-validate.yml` remains
  the configuration-only entry point (also `just esxi-validate`).
- `just packer-validate TARGET` and `just packer-build TARGET` delegate to the
  existing Packer wrapper, preserving explicit target selection and build options.
  Omitting VM files selects all target files in sorted order; existing VMs are not
  skipped, and the first failure stops the batch. `--force` can replace existing
  VMs; prefer explicit file selection when adding VMs to a working environment.

When changing these wrappers, verify compatibility with `just` 1.21, argument
forwarding, and preservation of existing secrets. Run
`python3 -m unittest discover -s tests` and `just --list`.
Do not run VM builds to test wrapper changes.

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
- `vm_disk_mb` and `vm_disk_thin_provisioned` configure the first (OS) disk.
  `vm_data_disk_mb` enables a second disk when greater than zero (default zero);
  `vm_data_disk_thin_provisioned` defaults to false for thick provisioning.
  Worker examples use a 204800 MB thin OS disk and a 512000 MB thick data disk.
  Autoinstall explicitly selects `/dev/sda`, the first disk on the PVSCSI
  controller, leaving the data disk unformatted. Revisit that match if changing
  controller types or disk ordering. Configure the new data disk's stable ID in
  host variables before running the separate Longhorn disk preparation workflow.
- Keep real `*.pkrvars.hcl` files untracked.
- Update sanitized examples whenever required variables change.
- Select exactly one build scope with `--target`: `esxi-6.7` for management VMs
  or `esxi-8` for worker VMs. The wrapper derives the matching common file and
  VM directory and rejects cross-target VM files.
- Install the managed SSH public key during autoinstall. The password is a
  temporary Packer bootstrap credential, not the long-term operator credential.
- Treat Packer 1.16.1 and the vSphere plugin 1.2.7 as the standalone-ESXi
  qualification toolchain. Plugin 2.5.0 requires a vCenter CIS REST login and
  fails during `StepConnect` against both standalone hosts. Re-evaluate the
  plugin pin after introducing vCenter or retiring the standalone workflow.
- Keep the qualified ESXi 6.7 boot timing in its common file: `boot_wait =
  "20s"` and `boot_keygroup_interval = "1500ms"`. Occasional recoverable
  virtual-key release warnings may appear, but a successful build must fetch
  cloud-init data, connect over SSH, provision, and shut down cleanly.

### Validate

```bash
scripts/validate-packer.sh
packer/build-ubuntu-vms.sh --target esxi-6.7 --validate-only
packer/build-ubuntu-vms.sh --target esxi-8 --validate-only
```

The reusable script validates all committed examples and is also run by CI.
The wrapper validates local values for one target. A Packer build creates or
replaces infrastructure; omit `--validate-only` only after a separate operator
decision.

`--start-at` skips earlier files in the selected, ordered VM-variable list. It
does not restore an interrupted builder step or adopt a partially created VM;
inspect or clean up partial ESXi state before rebuilding.

Official references: [Packer init](https://developer.hashicorp.com/packer/docs/commands/init),
[Packer validate](https://developer.hashicorp.com/packer/docs/commands/validate),
[input variable validation](https://developer.hashicorp.com/packer/docs/templates/hcl_templates/variables),
and the [VMware vSphere ISO builder](https://developer.hashicorp.com/packer/integrations/vmware/vsphere/latest/components/builder/vsphere-iso).

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
- `managed_vm_esxi_ownership`: authoritative ESXi-to-VM ownership map
- `managed_vm_names`: complete VM list derived from the ownership map
- `esxi_managed_vm_names`: per-ESXi list derived at execution time
- `vm_power_state`
- `vm_power_enable_force`: boolean, defaults to false; pass JSON extra variables
  such as `-e '{"vm_power_enable_force": true}'` when resuming a suspended VM
  with `powered-on`. This maps directly to the VMware module's `force` option.
- `esxi_allowed_power_states` in `group_vars/vmware_esxi.yml`
- `just vm-power-states`, `just vm-power VM STATE`, and `just vm-power-all STATE`
  wrap existing power operations. Bulk scope is explicit; `--limit` selects owning
  ESXi inventory hosts. Single-VM power and deletion requests fail when the
  selected lifecycle hosts exclude the VM owner; the error identifies the required host.
  If a limit matches no lifecycle hosts, Ansible runs no tasks; inspect
  `--list-hosts` before execution.
  State validation and VM ownership remain in Ansible.
- `just vm-delete VM CONFIRMATION` requires the exact VM name twice and fixes
  scope to one VM; append `--check` for an Ansible preview. It delegates to
  `05-vm-delete.yml` without changing the role's UUID or force controls.
- `vm_delete_enable_force`: boolean, defaults to false. For powered-on VM deletion,
  use `just vm-delete VM VM --check -e '{"vm_delete_enable_force": true}'`, review
  the candidate, then omit `--check` to execute. Force may power off the VM and
  does not provide graceful guest shutdown or Kubernetes decommissioning.
  There is no recipe `--force` flag; `-e vm_delete_enable_force=true` supplies a
  string and fails the role's boolean validation. Force retains name, ownership,
  uniqueness, and optional UUID safeguards. See the
  [deletion examples](../README.md#vm-deletion-shortcut) and official
  [module force semantics](https://docs.ansible.com/projects/ansible/latest/collections/community/vmware/vmware_guest_module.html#parameter-force).
- `vm_delete_confirm`, `vm_delete_confirm_name`
- Optional UUID and delete-all confirmations

### Inspect ownership and power targets

`ansible-inventory --host` can display the literal Jinja expression for a
derived variable. This is expected because `esxi_managed_vm_names` depends on
the current `inventory_hostname`. Use the debug module to evaluate it in each
ESXi host's context:

```bash
ansible managed_vm_esxi \
  -m ansible.builtin.debug \
  -a 'var=esxi_managed_vm_names'
```

Use these keys when reasoning about scope:

| Key | Meaning |
|---|---|
| `managed_vm_esxi` | ESXi inventory group allowed to manage VM lifecycle |
| `managed_vm_esxi_ownership` | Source-of-truth mapping from ESXi aliases to owned VM aliases |
| `managed_vm_names` | Flattened list of every managed VM |
| `esxi_managed_vm_names` | VMs owned by the current ESXi host |
| `vm_power_name` | One explicitly selected managed VM |
| `scope=all` | Select every managed VM; each ESXi processes only its own list |
| `vm_power_state` | Requested state, such as `powered-on` or `powered-off` |

Preview one VM without changing its power state:

```bash
ansible-playbook playbooks/04-vm-power.yml \
  --check \
  -e vm_power_name=ubuntu_24.04-wrk-01 \
  -e vm_power_state=powered-on
```

Preview all managed VMs:

```bash
ansible-playbook playbooks/04-vm-power.yml \
  --check \
  -e scope=all \
  -e vm_power_state=powered-on
```

Do not infer evaluated ownership from an unresolved `ansible-inventory --host`
value. Use the debug command above or the playbook's check-mode output.

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
- `playbooks/99-guest-site.yml` (also available as `just guest-prepare`; accepts Ansible options)

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
just guest-prepare --check --limit <inventory-host>
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

### Platform shortcuts

| Recipe | Canonical playbook | Selected inventory hosts |
|---|---|---|
| `kubernetes-inventory` | `07-kubespray-inventory.yml` | `control_node` |
| `kubernetes-install` | `08-kubespray-install.yml` | `control_node` |
| `kubernetes-prepare` | `10-kubernetes-node-prepare.yml` | `managed_vms` |
| `kubernetes-deploy` | `09-kubespray-deploy.yml` | `control_node` |
| `kubernetes-metallb` | `13-kubespray-metallb.yml` | `control_node` |
| `kubernetes-health` | `14-kubernetes-health.yml` | `control_node` |
| `longhorn-prepare` | `16-longhorn-node-prepare.yml` | `longhorn_nodes` |
| `argocd-bootstrap` | `19-argocd-bootstrap.yml` | `control_node` |

All recipes forward Ansible arguments literally without injecting enable flags.
They have no automatic `just` dependencies. The underlying deployment playbook
renders inventory and prepares Kubespray tooling before deployment; it does not
provision VMs or perform the complete guest workflow. Prepare credentials, guest
networking, and SSH first. Configure topology and deployment versions through the
existing inventory and role variables rather than the recipes.

Supply `kubespray_control_enable_cluster_deploy=true` for Kubernetes deployment
and `argocd_bootstrap_enable=true` for Argo CD bootstrap. The MetalLB playbook
itself enables a tagged deployment and applies pools without an additional
operator enable flag. The health playbook refreshes the operator kubeconfig.
Longhorn formatting remains a separate explicit opt-in for a verified blank disk.

Outer `--limit` selects the hosts in the table, not the nodes targeted by nested
Kubespray. In particular, limiting a control-node recipe to a worker can select no
hosts and perform no work. Inspect `--list-hosts` before using limits. Deployment
check mode is not an end-to-end simulation of Kubespray. Argo CD check mode only
validates local inputs and its version pin. Use the documented Kubespray lifecycle
for scaling or upgrades; these wrappers add no scaling or rolling-update logic.

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

Keep Kubespray runtime logs with the generated cluster state:

- deployment: `.generated/kubespray/production/kubespray-deploy.log`
- reset: `.generated/kubespray/production/kubespray-reset.log`
- optional `nohup` wrapper: `.generated/kubespray/production/kubespray-deploy-nohup.log`

The role initializes the deployment or reset log at the start of the matching
operation. Do not create duplicate Kubespray logs in the repository root or a
second `logs/` tree.

Deploy only with the explicit guard:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true
```

For a background run, keep only the outer wrapper output separate; the nested
Kubespray process continues to use the deployment log above:

```bash
nohup .venv/vmware/bin/ansible-playbook \
  playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  > .generated/kubespray/production/kubespray-deploy-nohup.log 2>&1 \
  < /dev/null &
```

`99-kubernetes-site.yml` prepares the controller and nodes and invokes this
guarded base-cluster deployment. It does not run `13-kubespray-metallb.yml` or
`14-kubernetes-health.yml`; apply MetalLB address pools and perform the final
health validation as explicit post-deployment steps. In contrast,
`99-platform-site.yml` already runs both steps and then performs the guarded
Argo CD bootstrap.

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

The shared settings include kube-vip leader-election timings. Production uses
the upstream kube-vip defaults `15/10/2` rather than Kubespray v2.31.0's
shorter `5/3/1` defaults. This is a tolerance measure for brief API stalls; it
does not repair slow ESXi storage, etcd request latency, or API HTTP 500
responses. Treat recurring etcd or API failures as a separate control-plane
storage incident.

Use the dedicated [kube-vip per-node interface guide](kube-vip-per-node-interface.md) for change, verification, failover, troubleshooting, and rollback procedures.
That guide also contains the authoritative scope, acceptance criteria, and
official upstream references for the timing configuration.

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
- Metrics Server, cert-manager, registry, and Helm enable flags
- `kubespray_inventory_enable_argocd` must remain `false`; Argo CD v3 is
  bootstrapped by `19-argocd-bootstrap.yml` from the GitOps source of truth
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
- `scripts/setup-kubernetes-client.py` and `just kubernetes-client-setup`

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

### Health checks from another checkout or control node

The default client paths are `.generated/kubespray/production/artifacts/kubectl`
and `admin.conf` (with the configured cluster name replacing `production`).
`.generated/` is Git-ignored: cloning or pulling this repository does not restore
these files. Missing files stop validation before cluster health is assessed.
Do not redeploy Kubernetes solely to restore local client files.

To restore from a trusted original control node, use the explicit source host
and absolute artifacts directory (adjust both for your environment):

```bash
just kubernetes-client-setup sysadmin@172.16.6.20 \
  /home/sysadmin/esxi-ansible-iac/.generated/kubespray/production/artifacts
.generated/kubespray/production/artifacts/kubectl \
  --kubeconfig .generated/kubespray/production/artifacts/admin.conf config current-context
# After confirming the intended cluster:
just kubernetes-health
```

Run this on the machine serving as Ansible's local control node. The helper uses
noninteractive SSH authentication and requires a previously verified known-host entry;
establish SSH access first. Password/passphrase prompts are disabled, so use an
available SSH key or agent. Terminal allocation, agent/X11 forwarding, and port
forwarding are disabled for transfers; host-key checking remains enabled. Optional
`--identity /path/to/key` selects an SSH key, and `--cluster NAME` changes the local
artifact directory to match `kubespray_cluster_name`; the remote path stays explicit.
For a nondefault cluster, also select that cluster in inventory or pass
`-e kubespray_cluster_name=NAME` to subsequent health checks.
Only use a trusted source: the helper executes the downloaded client locally.

The helper checks matching Linux OS/architecture, the executable header, client
version execution, and the kubeconfig's current-context references. Every cluster
and user entry is inspected, including inactive entries. Kubeconfig must be
self-contained, without external certificate/key files or credential plugins.
This restriction is specific to this restoration helper; Kubernetes itself
supports external files and credential plugins.
It stages both files privately, installs only after validation, and preserves any
existing artifacts (including symlinks). To refresh credentials, securely back up
and move both old files first, then rerun setup. It sets directory mode 0700,
`kubectl` mode 0755, and `admin.conf` mode 0600. It does not print credentials,
contact the Kubernetes API, modify `~/.kube/config`, or redeploy the cluster.
Before health checks, verify the intended cluster using the installed client;
local validation does not prove API reachability or credential validity.
It also does not authenticate the binary independently of the trusted SSH source,
verify certificate expiry, or check client/server version skew. Restore only from
an operator-controlled source with the appropriate client release. Kubernetes
supports `kubectl` within one minor version of every API server it contacts.
After confirming the intended context, check client/server versions with:

```bash
.generated/kubespray/production/artifacts/kubectl \
  --kubeconfig .generated/kubespray/production/artifacts/admin.conf version -o yaml
```

This command contacts the API. If the source artifacts grant cluster-admin
access, transfer them only to an authorized administrative machine; restoration
does not reduce their privileges. Do not use kubeconfig or downloaded executables
from an untrusted source.

Official references:

- [Kubernetes kubeconfig trust, contexts, and file references](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/)
- [Kubernetes client/server version skew policy](https://kubernetes.io/releases/version-skew-policy/)
- [OpenSSH client configuration](https://man.openbsd.org/ssh_config)


If this control node already has a compatible `kubectl` and a working kubeconfig
for the intended cluster, verify their availability and selected cluster first:

```bash
command -v kubectl
test -r "$HOME/.kube/config"
kubectl --kubeconfig "$HOME/.kube/config" config current-context
kubectl --kubeconfig "$HOME/.kube/config" get nodes
```

After those checks succeed, reuse the existing client paths:

```bash
just kubernetes-health \
  -e "kubernetes_health_kubectl=$(readlink -e "$(command -v kubectl)")" \
  -e "kubernetes_health_kubeconfig=$HOME/.kube/config"
```

Use the actual kubeconfig path if different. The role copies it to
`kubernetes_health_operator_kubeconfig` (default `~/.kube/config`); set that
variable to a separate destination if you need to preserve a different existing
operator configuration. Paths refer to the Ansible `control_node` host.

If no working client configuration exists here, securely transfer the deployment
artifacts from the original control node, keeping `admin.conf` private (mode
0600). Verify its API endpoint is reachable from the new machine and that the
client binary matches its OS/architecture. Do not commit kubeconfig credentials.
The earlier `control_plane_kubeconfig` role installs user configs on the remote
control-plane nodes; it does not fetch those files to this checkout.

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

`just longhorn-prepare [Ansible options]` invokes the canonical preparation
playbook. Use `--check --limit <worker>` first; formatting stays disabled unless
explicitly enabled for a verified blank disk.

### First-time Longhorn disk setup

Run these read-only commands **on each worker** to identify its dedicated data
disk and the physical disk backing the OS:

```bash
lsblk -p -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
lsblk -s -p -o NAME,TYPE,SIZE "$(findmnt -n -o SOURCE /)"
ls -l /dev/disk/by-id/
```

Select the dedicated data disk by its identity, size, layout, and usage. It must
be absent from the root-device ancestry and must not contain data you need to
preserve. Do not assume `/dev/sdb` is always the data disk. Devices presented by
existing Longhorn volumes are not candidates for the backing data disk.

After verifying the device, list its stable identifiers. The example below uses
`/dev/sdb`; substitute the device you identified:

```bash
find -L /dev/disk/by-id -maxdepth 1 -samefile /dev/sdb -print
```

For a VMware data disk, select its whole-disk `scsi-36000...` or `wwn-0x...`
identifier, without a partition suffix such as `-part1`. Confirm that the chosen
symlink resolves to an existing verified disk with `readlink -e <full-by-id-path>`
(replace the placeholder with the complete path).
If no stable identifier exists, resolve device identification before enabling
preparation; do not substitute a `/dev/sdX` path.

On the **control node**, set the complete identifier in that worker's
`inventories/production/host_vars/<worker>/longhorn.yml`:

```yaml
longhorn_node_prepare_data_device: /dev/disk/by-id/REPLACE_WITH_VERIFIED_DISK_ID
```

Each worker needs its own verified identifier. Re-identify the disk after VM
recreation or disk replacement; the committed production IDs are not templates
for new disks. Production already enables `longhorn_node_prepare_has_data_disk`
in `group_vars/longhorn_nodes.yml`; verify every selected worker's path before
running the playbook. For a new inventory, enable this setting only after
identifying the dedicated disks.

For a verified blank disk, preview and then initialize **one worker at a time**
from the control node. Replace the example worker name as appropriate:

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --limit ubuntu_24.04-wrk-01 --check \
  -e '{"longhorn_node_prepare_enable_disk_format": true}'

# Run only after reviewing a successful preview:
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --limit ubuntu_24.04-wrk-01 \
  -e '{"longhorn_node_prepare_enable_disk_format": true}'
```

Keep formatting disabled in persistent configuration. Existing prepared disks
use the normal procedure below without the formatting override. The role rejects
root devices, partitioned disks, conflicting mounts, and incompatible detected
filesystems. These checks supplement operator identification; a missing filesystem
signature alone does not prove a disk contains no valuable data.

The role mounts the filesystem by UUID and verifies its UUID and filesystem type.
On the worker, confirm both the active mount and persistent fstab entry:

```bash
findmnt --mountpoint /var/lib/longhorn -o SOURCE,UUID,FSTYPE,TARGET,OPTIONS
findmnt --fstab --target /var/lib/longhorn -o SOURCE,TARGET,FSTYPE,OPTIONS
```

Use the configured data path if it differs from `/var/lib/longhorn`. This workflow
prepares host storage; in-cluster Longhorn deployment remains owned by GitOps.

### Safe update procedure

```bash
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --check --limit <worker>
ansible-playbook playbooks/16-longhorn-node-prepare.yml \
  --limit <worker>
```

Check mode runs read-only disk, kernel, and mount probes and retains disk safety
checks. For an approved blank disk, it reports the planned format and mount; UUID
and mount verification wait until the filesystem exists. Existing filesystems
can preview mount changes, and existing mounts are verified. Checks for installed
commands and an active iSCSI daemon run only during normal execution because
package installation and service activation are only predicted in check mode.

Disk formatting must remain disabled unless a verified, empty target device is intentionally being initialized. Before node maintenance, confirm Longhorn replica health, free capacity, and data locality. In-cluster Longhorn deployment and volumes remain owned by GitOps.

### Longhorn disk troubleshooting

| Symptom | Checks and next action |
|---|---|
| No suitable `/dev/disk/by-id/` entry | Confirm that the dedicated virtual disk is attached and visible in `lsblk`. Check its identity exposure in the VM configuration before proceeding. Do not fall back to `/dev/sdX`. |
| Configured ID is missing or stale | Run `ls -l` and `readlink -e` on the configured path. Rediscover the disk after replacement or VM recreation, then update only the affected worker's host variables. |
| Root-device or disk-layout assertion fails | Recheck root ancestry and disk partitions. This role expects a dedicated whole disk with no child partitions; do not erase partitions to bypass the check. |
| Blank disk rejected | Verify disk ownership and contents, then use the temporary formatting override from the first-time procedure for both preview and execution. |
| Filesystem type differs | Inspect the existing filesystem and its data. Choose the intended supported filesystem configuration or plan a migration; do not force-format it. |
| Mount source differs or disk is mounted elsewhere | Compare the configured device, active mount, and fstab UUID. Resolve the ownership or mount conflict before rerunning. |
| Unmounted data directory contains files | Determine whether the intended data disk is missing or data was written to the OS filesystem. Do not delete the directory or mount over its contents to clear the assertion. |
| Normal health checks fail after a successful preview | Check the specific failed command, iSCSI service, kernel support, or mount propagation. Preview does not execute every post-installation check. |

On the affected worker, use these read-only checks to inspect a mount or service
failure. Substitute the configured path if it differs:

```bash
findmnt --mountpoint /var/lib/longhorn -o SOURCE,UUID,FSTYPE,TARGET,OPTIONS
findmnt --fstab --target /var/lib/longhorn -o SOURCE,TARGET,FSTYPE,OPTIONS
systemctl status iscsid.service --no-pager
journalctl -u iscsid.service -n 50 --no-pager
```

### Longhorn verification checklist

Before declaring host preparation complete, verify each worker:

- Its configured stable ID resolves to the intended disk outside the OS ancestry.
- The active mount uses that disk, the configured filesystem, and the configured
  data path; fstab uses the same filesystem UUID.
- Normal execution finishes with `failed=0` and `unreachable=0`. A reconciled
  worker normally reports `changed=0`; first-time preparation may report changes.
  Kernel-module loading uses `changed_when: false`, so the recap is not proof
  that no command ran or runtime state changed.
- Read the failed task rather than relying only on recap counts. In preview,
  command prerequisites and active-iSCSI validation are intentionally skipped.

After Longhorn is deployed, check cluster storage separately from host preparation.
Run these read-only commands from a machine with the intended kubeconfig:

```bash
kubectl config current-context
kubectl -n argocd get applications.argoproj.io longhorn
kubectl -n longhorn-system get pods
kubectl -n longhorn-system get nodes.longhorn.io
kubectl -n longhorn-system get volumes.longhorn.io
kubectl -n longhorn-system get events --field-selector type=Warning --sort-by=.lastTimestamp
```

Check application sync and health, pod readiness and restart history, node/disk
readiness and scheduling, and each volume's health and replica placement. An
empty volume list does not test provisioning. A healthy status at one point in
time or successful host playbook does not establish sustained storage stability; investigate recent
probe failures, repeated restarts, or replica warnings. New clusters without the
Longhorn application should deploy it through GitOps before these checks.

### Longhorn disk replacement

This is a planned replacement procedure for a recoverable disk. If a disk has
failed and holds the only usable replica, stop and establish a volume recovery
or backup-restore plan before initializing anything. The host-preparation role
does not recover Longhorn volume data or evacuate replicas.

1. Identify the affected worker, physical disk, Longhorn disk entry, and volumes.
   Establish a usable recovery path and sufficient eligible replacement capacity.
2. Disable scheduling on the old Longhorn disk and request replica eviction.
   Wait for replicas and backing images to leave before removing the disk entry.
   Disabling scheduling alone does not move existing data. Follow the installed
   release's [disk removal](https://longhorn.io/docs/1.12.1/nodes-and-volumes/nodes/multidisk/)
   and [eviction](https://longhorn.io/docs/1.12.1/nodes-and-volumes/nodes/disks-or-nodes-eviction/)
   guidance; select the documentation version matching the deployment.
3. Confirm affected volumes retain the required healthy replicas elsewhere.
   If eviction stalls, resolve capacity or scheduling constraints first. With
   three workers and three replicas under hard node anti-affinity, the remaining
   two workers cannot accommodate all three replicas; additional eligible
   capacity may be required. See the upstream
   [eviction prerequisites](https://longhorn.io/kb/how-to-evict-node-during-capi-node-rolling-replacement/).
4. Coordinate workload and node maintenance, release use of the old mount, then
   unmount and replace the verified data disk. Do not detach an in-use disk or
   format a mounted filesystem. Preserve the old disk until recovery is verified.
5. Repeat [first-time discovery](#first-time-longhorn-disk-setup) and update that
   worker's stable ID. Confirm the mount path is available and contains no
   unexpected files. Preview and initialize only the verified blank replacement,
   with the temporary formatting override and a single-worker limit.
6. Verify the new filesystem UUID, fstab entry, active mount, and normal host
   checks. Reconcile the replacement disk in Longhorn through the operational
   workflow, then enable scheduling and verify replica rebuilds and volume health
   before replacing another disk. Do not copy old Longhorn disk identity metadata
   to make a fresh filesystem appear to be the removed disk.

## 12. Automated Argo CD v3 bootstrap

### Purpose

Completes an unattended platform deployment after Kubespray by installing the
Argo CD version pinned in `/opt/gitops-platform`, applying AppProjects and the
root Application, and handing continuous reconciliation to Argo CD.

### Ownership

- Kubespray owns the Kubernetes cluster and keeps `argocd_enabled` disabled.
- `roles/argocd_bootstrap/` is an idempotent bootstrap and recovery mechanism.
- `/opt/gitops-platform/clusters/production/argocd/resources` owns the Argo CD
  installation manifest and version.
- `argocd-runtime` owns continuous Argo CD reconciliation after bootstrap.

Do not copy the upstream Argo CD install manifest into this repository. The
bootstrap consumes the GitOps source directly so the version and patches have
one source of truth.

### Important controls

- `argocd_bootstrap_enable` defaults to `false` and must be explicitly enabled.
- `kubespray_inventory_enable_argocd` must remain `false`.
- `argocd_bootstrap_gitops_dir` defaults to `/opt/gitops-platform`.
- `argocd_bootstrap_expected_version` verifies the deployed Argo CD images.
- The generated Kubespray `kubectl` and `admin.conf` are used explicitly.

`just argocd-bootstrap [Ansible options]` delegates to `19-argocd-bootstrap.yml`.
It preserves the explicit `argocd_bootstrap_enable=true` gate, GitOps manifest
paths, expected version pin, and live readiness/rollout checks. In check mode,
only local inputs and the version pin are validated.

### Use and validate

Preview local prerequisites without modifying the cluster:

```bash
ansible-playbook playbooks/19-argocd-bootstrap.yml \
  --check -e argocd_bootstrap_enable=true
```

Bootstrap a new installation or verify an existing handoff:

```bash
ansible-playbook playbooks/19-argocd-bootstrap.yml \
  -e argocd_bootstrap_enable=true
```

Run the complete deployment workflow:

```bash
ansible-playbook playbooks/99-platform-site.yml \
  -e kubespray_control_enable_cluster_deploy=true \
  -e argocd_bootstrap_enable=true
```

The role stops before mutation unless the API is ready and every node is
Ready. It performs a server-side dry-run, waits for all Argo CD workloads,
applies the security projects before the root Application, and verifies the
pinned Argo CD image version. Vault initialization and unsealing remain a
separate security boundary unless a supported auto-unseal service is adopted.

## 13. Project synchronization

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

## 14. CI and repository quality

### Purpose

Ensures inventory can load and committed Packer, YAML, and Ansible content
remains valid.

### Owned files

- `tests/`
- `.github/workflows/validate.yml`
- `.pre-commit-config.yaml`
- `scripts/validate-packer.sh`
- `scripts/check-markdown-links.py`
- `.yamllint.yml`
- `.ansible-lint`
- `requirements-dev.txt`
- `requirements.yml`

### Current checks

- Offline regression tests for setup, wrappers, VM owner selection, and Longhorn previews
  (CI installs `just` so wrapper tests run)
- Production inventory graph
- Packer formatting and every committed ESXi/VM example combination
- YAML lint
- Ansible lint
- Syntax check for every playbook
- Relative Markdown file and heading-fragment validation

### Local validation

```bash
source .venv/vmware/bin/activate
python -m unittest discover -s tests -v
scripts/validate-packer.sh
python3 scripts/check-markdown-links.py
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
