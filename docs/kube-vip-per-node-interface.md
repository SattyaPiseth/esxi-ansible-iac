# kube-vip Per-Node Interface Configuration

## Overview

This document describes the Kubernetes networking correction required after restoring the control-plane virtual machines from VMware ESXi 8 to VMware ESXi 6.7.

The restored virtual machines do not all expose the Kubernetes-facing NIC using the same Linux interface name.

Current interface mapping:

| Node | Kubernetes Primary Interface |
|---|---|
| `ubuntu_24.04-mgmt-01` | `ens33` |
| `ubuntu_24.04-mgmt-02` | `ens192` |
| `ubuntu_24.04-mgmt-03` | `ens192` |
| `ubuntu_24.04-wrk-01` | `ens33` |
| `ubuntu_24.04-wrk-02` | `ens33` |
| `ubuntu_24.04-wrk-03` | `ens33` |

The Linux interfaces must **not** be renamed or reconfigured simply to make all nodes identical.

Instead, the Ansible source of truth must define the Kubernetes primary interface on a per-node basis.

The same per-host interface is then used by:

- kube-vip
- Kubespray generated inventory
- NIC offload configuration
- Kubernetes health checks

This avoids introducing unnecessary networking, etcd, or Kubernetes API availability risk on already-running control-plane nodes.

---

## Objective

Replace the previous global interface assumption:

```yaml
kube_vip_interface: ens33
```

with a node-specific configuration.

The required kube-vip mapping is:

```text
ubuntu-24-04-mgmt-01 -> ens33
ubuntu-24-04-mgmt-02 -> ens192
ubuntu-24-04-mgmt-03 -> ens192
```

Workers currently continue to use:

```text
ens33
```

The canonical Ansible variable is:

```yaml
kubernetes_primary_interface
```

This variable becomes the source of truth for all Kubernetes-facing NIC configuration.

---

## Important Constraints

Do not:

- rename `ens33` to `ens192`;
- rename `ens192` to `ens33`;
- change Netplan merely to standardize interface names;
- change the global kube-vip interface from `ens33` to `ens192`;
- assume every Kubernetes node has the same interface name;
- introduce another independent NIC-selection variable;
- perform a kube-vip failover test before all three kube-vip Pods are healthy.

Interface standardization may be considered during a future VM rebuild.

For the current production cluster, per-node interface configuration is the safer design.

---

## Repository

Run all repository operations from:

```bash
cd /home/sysadmin/esxi-ansible-iac
```

The repository should remain the source of truth.

Avoid permanent live-only changes that are not represented in Ansible.

---

## 1. Configure the Interface Per Host

Update:

```text
inventories/production/hosts.yml
```

> Important: this file previously contained mixed CRLF/LF line endings. Save the updated file using **LF line endings**.

Add:

```yaml
ubuntu_24.04-mgmt-01:
  ansible_host: 172.16.6.20
  kubernetes_primary_interface: ens33

ubuntu_24.04-mgmt-02:
  ansible_host: 172.16.6.21
  kubernetes_primary_interface: ens192

ubuntu_24.04-mgmt-03:
  ansible_host: 172.16.6.22
  kubernetes_primary_interface: ens192

ubuntu_24.04-wrk-01:
  ansible_host: 172.16.6.23
  kubernetes_primary_interface: ens33

ubuntu_24.04-wrk-02:
  ansible_host: 172.16.6.24
  kubernetes_primary_interface: ens33

ubuntu_24.04-wrk-03:
  ansible_host: 172.16.6.25
  kubernetes_primary_interface: ens33
```

Every Kubernetes node managed by this inventory must define:

```yaml
kubernetes_primary_interface
```

---

## 2. Remove the Global kube-vip Interface

Update:

```text
inventories/production/group_vars/all.yml
```

Keep:

```yaml
kubespray_inventory_enable_kube_vip: true
kubespray_inventory_kube_vip_address: 172.16.6.150
kubespray_inventory_dns_mode: coredns
```

Remove:

```yaml
kubespray_inventory_kube_vip_interface: ens33
```

The kube-vip interface must no longer be selected globally.

---

## 3. Make NIC Offload Configuration Per Host

In:

```text
inventories/production/group_vars/all.yml
```

change:

```yaml
guest_base_nic_offload_interface: ens33
```

to:

```yaml
guest_base_nic_offload_interface: "{{ kubernetes_primary_interface }}"
```

The NIC offload configuration therefore uses the same interface source of truth as kube-vip.

---

## 4. Render kube-vip Interface Into Each Kubespray Host

Update:

```text
roles/kubespray_inventory/templates/kubespray_inventory.ini.j2
```

Each generated host entry must include:

```jinja2
kube_vip_interface={{ hostvars[vm_name].kubernetes_primary_interface }}
```

The generated host line should follow this structure:

```jinja2
{{ kubespray_inventory_node_names[vm_name] | default(vm_name | replace('_', '-') | replace('.', '-')) }} ansible_host={{ hostvars[vm_name].ansible_host }} ip={{ hostvars[vm_name].ansible_host }} access_ip={{ hostvars[vm_name].ansible_host }} kube_vip_interface={{ hostvars[vm_name].kubernetes_primary_interface }}
```

This creates host-specific Kubespray variables such as:

```text
ubuntu-24-04-mgmt-01 ... kube_vip_interface=ens33
ubuntu-24-04-mgmt-02 ... kube_vip_interface=ens192
ubuntu-24-04-mgmt-03 ... kube_vip_interface=ens192
```

---

## 5. Remove kube-vip Interface From Generated Group Variables

Update:

```text
roles/kubespray_inventory/templates/k8s_cluster.yml.j2
```

Keep:

```yaml
kube_vip_lb_enable: {{ kubespray_inventory_enable_kube_vip_lb | bool | lower }}
kube_vip_address: "{{ kubespray_inventory_kube_vip_address }}"
```

Remove:

```yaml
kube_vip_interface: "{{ kubespray_inventory_kube_vip_interface }}"
```

The generated Kubespray group variables must not override the interface selected for individual hosts.

---

## 6. Remove the Obsolete Role Default

Update:

```text
roles/kubespray_inventory/defaults/main.yml
```

Remove:

```yaml
kubespray_inventory_kube_vip_interface: "{{ kubespray_kube_vip_interface | default('') }}"
```

Keep the remaining kube-vip defaults unchanged.

---

## 7. Validate Interface Configuration for Every Host

Update:

```text
roles/kubespray_inventory/tasks/validate.yml
```

Each managed VM must define both:

```yaml
ansible_host
kubernetes_primary_interface
```

Validation should include:

```yaml
- name: Validate Kubespray node hostvars
  ansible.builtin.assert:
    that:
      - hostvars[item].ansible_host is defined
      - hostvars[item].ansible_host | string | length > 0
      - hostvars[item].kubernetes_primary_interface is defined
      - hostvars[item].kubernetes_primary_interface | string | length > 0
    fail_msg: >-
      Managed VM '{{ item }}' must define ansible_host and
      kubernetes_primary_interface.
  loop: "{{ kubespray_inventory_all_vm_names }}"
```

Remove the previous global kube-vip interface assertion:

```yaml
- not (kubespray_inventory_enable_kube_vip | bool) or kubespray_inventory_kube_vip_interface | length > 0
```

The interface is now validated at host level instead.

---

## 8. Update Kubernetes Health Validation

Update:

```text
roles/kubernetes_health/tasks/network.yml
```

Replace the global interface:

```yaml
"{{ kubernetes_health_nic_offload_interface }}"
```

with the interface belonging to the delegated host:

```yaml
"{{ hostvars[item].kubernetes_primary_interface }}"
```

The resulting command should effectively operate as:

```yaml
- ethtool
- -k
- "{{ hostvars[item].kubernetes_primary_interface }}"
```

This ensures each node is checked against its actual interface.

---

## 9. Remove the Obsolete Health Variable

Update:

```text
roles/kubernetes_health/defaults/main.yml
```

Remove:

```yaml
kubernetes_health_nic_offload_interface: "{{ guest_base_nic_offload_interface | default('ens33') }}"
```

Keep:

```yaml
kubernetes_health_validate_nic_offloads: "{{ guest_base_enable_nic_offloads_disabled | default(false) }}"
kubernetes_health_enable_lb_smoke_test: false
```

There should no longer be an independent health-check interface variable.

---

## 10. Validate Ansible Syntax

Before rendering or applying anything:

```bash
cd /home/sysadmin/esxi-ansible-iac
```

Run:

```bash
ansible-playbook   -i inventories/production/hosts.yml   playbooks/07-kubespray-inventory.yml   --syntax-check
```

Expected result:

```text
playbook: playbooks/07-kubespray-inventory.yml
```

with no syntax or variable errors.

Do not continue if the syntax check fails.

---

## 11. Render the Kubespray Inventory

Run:

```bash
ansible-playbook   -i inventories/production/hosts.yml   playbooks/07-kubespray-inventory.yml
```

The generated production inventory should be created under:

```text
.generated/kubespray/production/
```

---

## 12. Verify Generated Host Variables

Inspect the generated `[all]` section:

```bash
sed -n '/^\[all\]/,/^\[kube_control_plane\]/p'   .generated/kubespray/production/inventory.ini
```

Expected relevant entries:

```text
ubuntu-24-04-mgmt-01 ... kube_vip_interface=ens33
ubuntu-24-04-mgmt-02 ... kube_vip_interface=ens192
ubuntu-24-04-mgmt-03 ... kube_vip_interface=ens192
```

Workers should resolve to:

```text
ubuntu-24-04-wrk-01 ... kube_vip_interface=ens33
ubuntu-24-04-wrk-02 ... kube_vip_interface=ens33
ubuntu-24-04-wrk-03 ... kube_vip_interface=ens33
```

---

## 13. Confirm the Global Value Is Gone

Run:

```bash
rg 'kube_vip_interface'   .generated/kubespray/production/group_vars   .generated/kubespray/production/inventory.ini
```

Expected behavior:

```text
.generated/kubespray/production/inventory.ini
```

contains the per-host values.

The generated Kubespray group-variable files must **not** contain a global:

```yaml
kube_vip_interface:
```

---

## 14. Review the Repository Diff

Before committing:

```bash
git status --short
git diff --check
git diff
```

`git diff --check` should return no whitespace errors.

Because `hosts.yml` previously contained mixed line endings, verify that the resulting diff does not contain unexpected unrelated content caused by CRLF conversion.

If the entire file appears changed only because of line endings, review carefully before committing.

---

## 15. Commit the Configuration

After validation:

```bash
git add   inventories/production/hosts.yml   inventories/production/group_vars/all.yml   roles/kubespray_inventory/templates/kubespray_inventory.ini.j2   roles/kubespray_inventory/templates/k8s_cluster.yml.j2   roles/kubespray_inventory/defaults/main.yml   roles/kubespray_inventory/tasks/validate.yml   roles/kubernetes_health/tasks/network.yml   roles/kubernetes_health/defaults/main.yml
```

Review staged changes:

```bash
git diff --cached --check
git diff --cached
```

Then commit according to the repository's normal change-management process.

Example commit message:

```text
fix(kubernetes): support per-node primary interfaces
```

---

## 16. Reconcile With Kubespray

After the source-of-truth changes are committed and the generated inventory is verified, run the repository's established Kubespray production workflow.

Do not run an unrelated or ad-hoc playbook.

The intended result is that Kubespray reconciles kube-vip using:

```text
mgmt-01 -> ens33
mgmt-02 -> ens192
mgmt-03 -> ens192
```

---

## 17. Verify Kubernetes Nodes

After reconciliation:

```bash
kubectl get nodes -o wide
```

Expected:

```text
ubuntu-24-04-mgmt-01   Ready
ubuntu-24-04-mgmt-02   Ready
ubuntu-24-04-mgmt-03   Ready
ubuntu-24-04-wrk-01    Ready
ubuntu-24-04-wrk-02    Ready
ubuntu-24-04-wrk-03    Ready
```

No control-plane node should become `NotReady`.

---

## 18. Verify kube-vip Static Pods

Run:

```bash
kubectl get pods -n kube-system -o wide | grep kube-vip
```

All three control-plane kube-vip Pods must be healthy:

```text
kube-vip-ubuntu-24-04-mgmt-01   1/1   Running
kube-vip-ubuntu-24-04-mgmt-02   1/1   Running
kube-vip-ubuntu-24-04-mgmt-03   1/1   Running
```

Do not proceed to failover testing unless all three are:

```text
1/1 Running
```

---

## 19. Verify kube-vip Interface Selection

Inspect the kube-vip configuration or static Pod manifests on each control-plane node.

Required mapping:

```text
ubuntu-24-04-mgmt-01 -> ens33
ubuntu-24-04-mgmt-02 -> ens192
ubuntu-24-04-mgmt-03 -> ens192
```

The Kubernetes API VIP remains:

```text
172.16.6.150
```

---

## 20. Verify API and etcd Health

Run:

```bash
kubectl get --raw='/readyz?verbose'
```

Required checks include:

```text
[+]etcd ok
[+]etcd-readiness ok
...
readyz check passed
```

Verify the control-plane nodes remain healthy:

```bash
kubectl get nodes -o wide
```

If required, verify etcd directly on each control-plane node:

```bash
sudo systemctl status etcd --no-pager
sudo ss -lntp | grep -E ':2379|:2380'
```

Typical expected listeners are:

```text
NODE_IP:2379
NODE_IP:2380
127.0.0.1:2379
```

---

## 21. Controlled kube-vip Failover Test

Perform this only after:

- all Kubernetes nodes are `Ready`;
- all three kube-vip Pods are `1/1 Running`;
- `/readyz?verbose` passes;
- etcd is healthy;
- the repository-generated configuration has been verified.

First determine which control-plane node currently owns:

```text
172.16.6.150
```

The failover test must confirm that:

1. the current owner releases the VIP;
2. another healthy control-plane node acquires it;
3. the new owner uses its own configured interface;
4. Kubernetes API access remains available;
5. all three control-plane nodes remain `Ready`;
6. etcd quorum remains healthy.

Perform only one controlled failover action at a time.

Do not combine failover testing with VM migration, interface changes, or other infrastructure maintenance.

---

## Expected Final State

```text
                       Kubernetes primary NIC
                       │
ubuntu-24-04-mgmt-01 ──┴─ ens33
ubuntu-24-04-mgmt-02 ──┴─ ens192
ubuntu-24-04-mgmt-03 ──┴─ ens192

ubuntu-24-04-wrk-01  ──┴─ ens33
ubuntu-24-04-wrk-02  ──┴─ ens33
ubuntu-24-04-wrk-03  ──┴─ ens33
```

with:

```text
kubernetes_primary_interface
            │
            ├── kube-vip
            ├── generated Kubespray inventory
            ├── NIC offload configuration
            └── Kubernetes network health validation
```

There should be no remaining global assumption that all Kubernetes nodes use the same Linux interface name.

---

## Rollback

If the generated inventory is incorrect, do not run Kubespray.

Correct the Ansible source of truth and re-render first.

If a Kubernetes reconciliation results in kube-vip failure:

1. do not rename Linux interfaces;
2. retain the node's existing networking;
3. verify the affected host's `kubernetes_primary_interface`;
4. verify the generated `kube_vip_interface`;
5. recover kube-vip on one control-plane node at a time;
6. confirm Kubernetes API and etcd health before continuing.

Avoid simultaneous changes to multiple control-plane nodes.

---

## Summary

The cluster contains valid but heterogeneous Linux interface names following the VMware restoration.

The correct solution is not to standardize those interfaces on running nodes.

The correct solution is to model the Kubernetes primary interface explicitly per host:

```yaml
kubernetes_primary_interface
```

and propagate that value consistently through Ansible, Kubespray, kube-vip, NIC-offload configuration, and health checks.

This preserves the existing host networking while allowing kube-vip to operate correctly on every control-plane node.
