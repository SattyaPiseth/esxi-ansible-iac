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
kubespray_inventory_kube_vip_lease_duration: 15
kubespray_inventory_kube_vip_renew_deadline: 10
kubespray_inventory_kube_vip_retry_period: 2
```

The rendered cluster configuration enables kube-vip for the control-plane endpoint, enables ARP mode, and leaves kube-vip service mode disabled because MetalLB owns `LoadBalancer` addresses.

The generated group variables must contain the VIP and shared mode settings, but must not contain a global `kube_vip_interface`.

The `15/10/2` leader-election timings are kube-vip's documented defaults:
the lease remains valid for 15 seconds, the leader has 10 seconds to renew it,
and renewal/acquisition attempts use a 2-second retry period. These settings
tolerate short API or datastore pauses better than Kubespray's `5/3/1`
defaults. They do not repair a slow etcd datastore; investigate recurring API
HTTP 500 responses, etcd timeouts, or sustained disk latency separately.

### Scope and limitations of the timing change

This configuration is a resilience mitigation, not a datastore repair:

- It gives the current kube-vip leader up to 10 seconds to renew a 15-second
  lease instead of abandoning leadership after 3 seconds.
- It reduces avoidable VIP movement and clean kube-vip restarts during short
  API stalls.
- It does not reduce ESXi datastore latency, speed up etcd writes, eliminate
  API HTTP 500 responses, or guarantee that a stall longer than the renewal
  deadline will preserve leadership.

The source variables render to Kubespray's supported
`kube_vip_leaseduration`, `kube_vip_renewdeadline`, and
`kube_vip_retryperiod` variables. The repository validates the required
ordering `retry period < renew deadline < lease duration` before rendering.

Consider the mitigation effective only when, after reconciliation and during a
representative observation period:

1. the live kube-vip Pods show `15/10/2`;
2. kube-vip restart counters stop increasing during brief API pauses;
3. the API VIP remains reachable during those pauses; and
4. etcd timeout and API HTTP 500 events are tracked independently until the
   storage bottleneck is corrected.

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

### kube-vip repeatedly restarts

First determine whether kube-vip is the cause or is reacting to an unhealthy
API. A lost leader lease followed by a clean container exit is normally a
symptom of API or etcd latency.

```bash
kubectl get --raw='/readyz?verbose'
kubectl -n kube-system logs --selector=k8s-app=kube-vip --previous --tail=100
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
ansible kube_control_plane -b -m ansible.builtin.shell \
  -a 'iostat -xz 1 3'
```

High disk `await`, sustained utilization, `etcdserver: request timed out`, or
API readiness HTTP 500 responses identify a control-plane storage/API problem.
Do not keep increasing leader-election timings to conceal that condition.

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

## Official references

- [kube-vip flags and environment variables](https://kube-vip.io/docs/installation/flags/) documents the `15/10/2` leader-election defaults and corresponding environment variables.
- [Kubespray v2.31.0 kube-vip defaults](https://github.com/kubernetes-sigs/kubespray/blob/v2.31.0/roles/kubernetes/node/defaults/main.yml) and its [static Pod template](https://github.com/kubernetes-sigs/kubespray/blob/v2.31.0/roles/kubernetes/node/templates/manifests/kube-vip.manifest.j2) document the supported variables consumed by this repository.
- [Kubernetes: Operating etcd clusters](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/) explains that etcd stability is sensitive to resource, network, and disk I/O starvation.
- [etcd hardware recommendations](https://etcd.io/docs/v3.5/op-guide/hardware/) and [etcd tuning](https://etcd.io/docs/v3.6/tuning/) explain why slow disk writes can cause request timeouts and temporary leader loss.

---

[Documentation index](README.md) · [Project README](../README.md) · [kube-vip feature ownership](feature-maintenance.md#8-kube-vip-control-plane-endpoint)
