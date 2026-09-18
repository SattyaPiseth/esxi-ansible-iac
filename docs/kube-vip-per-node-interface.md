# kube-vip Per-Node Interface Configuration

[Documentation index](README.md) · [Project README](../README.md) · [Feature maintenance guide](feature-maintenance.md#8-kube-vip-control-plane-endpoint)

## Purpose

This guide explains how this repository selects the network interface used by kube-vip, how that value is propagated into Kubespray, and how to verify a change safely.

The repository supports different Linux interface names across node classes. It does not rename interfaces or maintain a separate kube-vip interface setting.

## Current production configuration

The authoritative mapping is in `inventories/production/hosts.yml`:

| Ansible inventory host | Kubernetes node | Primary interface |
|---|---|---|
| `ubuntu_24.04-mgmt-01` | `ubuntu-24-04-mgmt-01` | `ens192` |
| `ubuntu_24.04-mgmt-02` | `ubuntu-24-04-mgmt-02` | `ens192` |
| `ubuntu_24.04-mgmt-03` | `ubuntu-24-04-mgmt-03` | `ens192` |
| `ubuntu_24.04-wrk-01` | `ubuntu-24-04-wrk-01` | `ens33` |
| `ubuntu_24.04-wrk-02` | `ubuntu-24-04-wrk-02` | `ens33` |
| `ubuntu_24.04-wrk-03` | `ubuntu-24-04-wrk-03` | `ens33` |

The Kubernetes API virtual IP is `172.16.6.150`.

Only control-plane nodes run kube-vip. Worker interface values are still rendered into the generated inventory because the same variable is also used for node networking, NIC-offload policy, and health validation.

## Source-of-truth model

Each managed Kubernetes node defines one variable:

```yaml
kubernetes_primary_interface: ens192
```

The value flows through the repository as follows:

```text
inventories/production/hosts.yml
        |
        +--> roles/kubespray_inventory
        |      |
        |      +--> .generated/kubespray/production/inventory.ini
        |             kube_vip_interface=<per-host value>
        |
        +--> guest_base_nic_offload_interface
        |      |
        |      +--> persistent NIC-offload configuration
        |
        +--> roles/kubernetes_health
               |
               +--> per-node interface and offload validation
```

Do not introduce a global `kube_vip_interface` or a second independent interface variable. A global value would override the per-host design and break mixed-interface environments.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `inventories/production/hosts.yml` | Authoritative interface for each node |
| `inventories/production/group_vars/all.yml` | kube-vip enablement, VIP, version, and shared networking policy |
| `roles/kubespray_inventory/tasks/validate.yml` | Requires an interface on every rendered node |
| `roles/kubespray_inventory/templates/kubespray_inventory.ini.j2` | Renders `kube_vip_interface` per host |
| `roles/kubespray_inventory/templates/k8s_cluster.yml.j2` | Renders shared kube-vip settings without a global interface |
| `roles/kubernetes_health/tasks/network.yml` | Validates the interface assigned to each node |

Generated content under `.generated/` is not a durable source of truth. Never edit it by hand.

## Shared kube-vip settings

The production variables currently include:

```yaml
kubespray_inventory_enable_kube_vip: true
kubespray_inventory_kube_vip_version: "1.0.4"
kubespray_inventory_kube_vip_address: 172.16.6.150
```

The rendered cluster configuration enables kube-vip for the control-plane endpoint, enables ARP mode, and leaves kube-vip service mode disabled because MetalLB owns `LoadBalancer` addresses.

The generated group variables must contain the VIP and shared mode settings, but must not contain a global `kube_vip_interface`.

## When to change an interface

Change `kubernetes_primary_interface` only when the interface carrying the node's Kubernetes address has genuinely changed, such as after:

- rebuilding or restoring a VM;
- changing its virtual NIC model or PCI position;
- moving the Kubernetes network to another NIC;
- changing the guest's network configuration deliberately.

Do not change it merely to make interface names identical across nodes.

## Safe change procedure

### 1. Confirm the live interface

On the affected node, identify the interface that owns its inventory address and reaches the LAN:

```bash
ip -br address
ip route
```

From the control node, display the configured address first:

```bash
ansible-inventory --host ubuntu_24.04-mgmt-01
```

Replace the inventory alias when checking another node. Do not infer the interface from another VM.

### 2. Update the inventory

Edit only the affected host in `inventories/production/hosts.yml`:

```yaml
ubuntu_24.04-mgmt-01:
  ansible_host: 172.16.6.20
  kubernetes_primary_interface: ens192
```

Keep the interface name as a host variable under `managed_vms`.

### 3. Validate and render

Run from the repository root:

```bash
ansible-inventory --graph
ansible-playbook playbooks/07-kubespray-inventory.yml --syntax-check
ansible-playbook playbooks/07-kubespray-inventory.yml
```

The render playbook validates that every Kubernetes node has both `ansible_host` and `kubernetes_primary_interface`.

### 4. Inspect generated values

```bash
sed -n '/^\[all\]/,/^\[kube_control_plane\]/p' \
  .generated/kubespray/production/inventory.ini

rg '^kube_vip_interface:' \
  .generated/kubespray/production/group_vars
```

Expected production host values:

```text
ubuntu-24-04-mgmt-01 ... kube_vip_interface=ens192
ubuntu-24-04-mgmt-02 ... kube_vip_interface=ens192
ubuntu-24-04-mgmt-03 ... kube_vip_interface=ens192
ubuntu-24-04-wrk-01  ... kube_vip_interface=ens33
ubuntu-24-04-wrk-02  ... kube_vip_interface=ens33
ubuntu-24-04-wrk-03  ... kube_vip_interface=ens33
```

The `rg` command should return no global interface from generated group variables. A nonzero `rg` exit status is expected when no match exists.

### 5. Preview guest reconciliation

An interface change also changes the target of the persistent NIC-offload policy. Preview the affected node:

```bash
ansible-playbook playbooks/99-guest-site.yml \
  --check --limit ubuntu_24.04-mgmt-01
```

Review the proposed network and offload changes before running without `--check`.

### 6. Reconcile through the supported workflows

Apply guest configuration to the affected node first:

```bash
ansible-playbook playbooks/99-guest-site.yml \
  --limit ubuntu_24.04-mgmt-01
```

For an interface change on an existing control-plane node, use the established Kubespray deployment workflow and its explicit guard:

```bash
ansible-playbook playbooks/09-kubespray-deploy.yml \
  -e kubespray_control_enable_cluster_deploy=true
```

Do not edit `/etc/kubernetes/manifests/kube-vip.yaml` manually. Kubespray must remain the owner of the static Pod configuration.

For control-plane maintenance, change and verify one node at a time. Confirm API and etcd health before proceeding to another node.

## Post-change verification

### Repository health check

```bash
ansible-playbook playbooks/14-kubernetes-health.yml
```

This validates the API through the VIP, expected kube-vip Pods, node readiness, and per-node network policy.

### Nodes and kube-vip Pods

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods \
  --selector=k8s-app=kube-vip -o wide
```

All three control-plane nodes must be `Ready`, and there must be one ready kube-vip Pod on each control-plane node.

### API readiness through the VIP

```bash
kubectl --server=https://172.16.6.150:6443 \
  get --raw='/readyz?verbose'
```

The result must end with `readyz check passed`. Investigate any failed etcd or API checks before continuing maintenance.

### Rendered or live interface

Verify the generated value:

```bash
rg 'kube_vip_interface=' \
  .generated/kubespray/production/inventory.ini
```

If live behavior differs from the generated configuration, inspect the kube-vip Pod on the affected control-plane node:

```bash
kubectl -n kube-system get pod \
  --selector=k8s-app=kube-vip -o yaml
```

Check the selected node, environment, arguments, recent events, and container logs. Do not patch the live Pod because the static Pod will be recreated from its manifest.

## Failover testing

Perform failover testing only when:

- every control-plane node is `Ready`;
- all three kube-vip Pods are ready;
- the API readiness endpoint passes through the VIP;
- etcd is healthy;
- kube-vip restart counters are stable;
- no unrelated cluster maintenance is in progress.

Test one control-plane node at a time and keep an existing API session available. A failover test is not required merely to render or review the inventory.

## Troubleshooting

### Interface does not exist

```bash
ansible ubuntu_24.04-mgmt-01 -b \
  -m ansible.builtin.command -a 'ip -br link'
```

Correct `kubernetes_primary_interface` in the inventory. Do not create or rename an interface simply to satisfy the variable.

### VIP is unreachable

Check, in order:

1. All control-plane nodes are ready.
2. kube-vip has one ready Pod per control-plane node.
3. The configured interface owns the node's Kubernetes/LAN address.
4. `172.16.6.150` is reserved and not assigned to another device.
5. ARP traffic is permitted on the network.
6. kube-proxy strict ARP remains enabled for IPVS mode.
7. Host firewalls and ESXi port-group policies have not changed.

Useful commands:

```bash
kubectl -n kube-system describe pod \
  --selector=k8s-app=kube-vip
kubectl -n kube-system logs \
  --selector=k8s-app=kube-vip --tail=200
ip neigh show 172.16.6.150
```

### NIC-offload validation fails

Confirm the inventory-selected interface and inspect its active features:

```bash
ansible ubuntu_24.04-mgmt-01 -b \
  -m ansible.builtin.command -a 'ethtool -k ens192'
```

Make persistent corrections through the guest roles. A one-time `ethtool -K` command does not survive every reboot or network reinitialization.

### Generated inventory is stale

Regenerate it from source:

```bash
ansible-playbook playbooks/07-kubespray-inventory.yml
```

Do not copy values from an old generated inventory back into `hosts.yml`.

## Rollback

If an inventory change was incorrect:

1. Restore the previous `kubernetes_primary_interface` in `hosts.yml`.
2. Regenerate the Kubespray inventory.
3. Review the generated host value.
4. Reconcile the affected guest if the offload target changed.
5. Run the guarded Kubespray deployment workflow.
6. Run `14-kubernetes-health.yml`.

Do not roll back by editing only the generated inventory or a live static Pod manifest.

## Pre-commit checks

```bash
git diff --check
PATH="$PWD/.venv/vmware/bin:$PATH" \
  .venv/vmware/bin/pre-commit run --all-files
```

Review the diff and confirm that no generated files, credentials, or unrelated runtime artifacts are staged.

---

[Documentation index](README.md) · [Project README](../README.md) · [kube-vip feature ownership](feature-maintenance.md#8-kube-vip-control-plane-endpoint)
