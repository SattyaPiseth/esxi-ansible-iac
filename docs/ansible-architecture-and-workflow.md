# Ansible Architecture and Workflow

[Documentation index](README.md) · [Project README](../README.md) · [Feature maintenance guide](feature-maintenance.md)

## Purpose

This document explains the Ansible design decisions that are specific to this
repository: how hosts and variables resolve, how VM requests reach the correct
ESXi host, how composite workflows execute, and which safety contracts apply.

Use the [project README](../README.md) for operator commands and the
[feature maintenance guide](feature-maintenance.md) for the complete playbook,
role, variable, and source-of-truth catalog. Those details are not duplicated
here so they cannot drift independently.

## Ownership boundaries

| Layer | Owner |
|---|---|
| Ubuntu VM creation | Packer |
| ESXi lifecycle and guest convergence | Ansible |
| Kubernetes installation and reset | Kubespray invoked by Ansible |
| Kubernetes node prerequisites and health checks | Ansible |
| In-cluster applications and Longhorn deployment | External GitOps repository |

Ansible does not replace Packer or GitOps. It supplies the infrastructure and
host-level convergence between those layers.

## Runtime contract

`ansible.cfg` defines the production inventory, local role path, collection
search path, Vault password file, host-key checking, and interpreter discovery.
`requirements-dev.txt` and `requirements.yml` are the authoritative version
pins; documentation deliberately does not repeat their versions.

Run the project as the regular `sysadmin` account. Collections are user-scoped,
so `sudo ansible-playbook` can load unrelated content from
`/root/.ansible/collections`. Managed-host privilege belongs in playbook
`become` settings.

Confirm the active runtime when troubleshooting:

```bash
whoami
ansible --version
ansible-config dump --only-changed
ansible-galaxy collection list
```

## Resolution model

Ansible resolves a run in this order:

```text
ansible.cfg
  -> inventory
  -> play hosts pattern
  -> variables for each inventory host
  -> roles and tasks
  -> task conditions, tags, and loops
  -> module execution
  -> registered results and assertions
```

The play-level `hosts:` value defines the initial set. `--limit`, tags, `when`
conditions, and loops can narrow it. Therefore, `--list-hosts` proves which
hosts enter a play, not that every task will execute on every listed host.

## Inventory and host identity

The production inventory is `inventories/production/hosts.yml`.

| Group | Meaning |
|---|---|
| `control_node` | Local orchestration, rendering, Kubespray, and health checks |
| `vmware_esxi` | All known ESXi API endpoints |
| `managed_vm_esxi` | ESXi endpoints permitted to manage project VMs |
| `managed_vms` | Complete managed Ubuntu guest boundary |
| `kube_control_plane` | Three control-plane and etcd guests |
| `kube_node` | Three worker guests |
| `k8s_cluster` | Control-plane and worker child groups |
| `longhorn_nodes` | Workers receiving Longhorn host prerequisites |
| `discovered_managed_vms` | Ephemeral hosts created during guest discovery |

An inventory alias, connection destination, and operating-system hostname are
different concepts:

```text
inventory_hostname: ubuntu_24.04-mgmt-01
ansible_host:       172.16.6.20
guest hostname:     ubuntu-24-04-mgmt-01
```

`inventory_hostname` is Ansible's stable identity and is used as a map key.
`ansible_host` is where the connection plugin connects.

Inspect group expansion without changing anything:

```bash
ansible-inventory --graph
ansible managed_vms --list-hosts
ansible managed_vm_esxi --list-hosts
```

## Variables and precedence

Variable placement expresses ownership:

| Source | Use |
|---|---|
| Role defaults | Reusable, conservative behavior |
| `group_vars/all.yml` | Environment-wide topology and cluster inputs |
| Group variables | Shared ESXi, guest, or Longhorn policy |
| `host_vars/<host>/main.yml` | One host's non-secret endpoint or placement data |
| Encrypted Vault files | Credentials and secrets |
| Play or task variables | Entry-point-specific behavior |
| Extra variables (`-e`) | Explicit operator request or confirmation |

The practical precedence direction is:

```text
role defaults
  < inventory group variables
  < inventory host variables
  < play/task variables
  < extra variables
```

Because `-e` has high precedence, treat every extra variable as part of the
change request. Avoid defining the same value in unrelated sibling groups.

`ansible-inventory --host` can leave derived Jinja expressions unresolved.
Evaluate a host-context value through Ansible instead:

```bash
ansible managed_vm_esxi \
  -m ansible.builtin.debug \
  -a 'var=esxi_managed_vm_names'
```

Do not publish complete resolved inventory output; it may contain decrypted
Vault data.

## ESXi ownership routing

`managed_vm_esxi_ownership` in `group_vars/all.yml` is the source of truth:

```yaml
managed_vm_esxi_ownership:
  vm_esxi_6.7:
    - ubuntu_24.04-mgmt-01
    - ubuntu_24.04-mgmt-02
    - ubuntu_24.04-mgmt-03
  vm_esxi_8.0:
    - ubuntu_24.04-wrk-01
    - ubuntu_24.04-wrk-02
    - ubuntu_24.04-wrk-03
```

The project derives:

- `managed_vm_names`: every managed VM;
- `esxi_managed_vm_names`: VMs owned by the current `inventory_hostname`.

`esxi_validate` requires every lifecycle ESXi host to have one non-empty,
duplicate-free ownership list. The flattened lists must match `managed_vms`
exactly and assign each VM once.

Lifecycle plays initially select both ESXi hosts. Each host filters the request
against its own list. A request for `ubuntu_24.04-wrk-01` skips ESXi 6.7 and
executes only on ESXi 8. This is explicit routing, not live discovery; a
duplicate VM on another ESXi host does not acquire ownership. Single-VM power
and deletion requests also check that the selected lifecycle hosts include the
owner. A limit selecting only the other ESXi host fails with the owner named in
the error. If no lifecycle hosts match at all, Ansible runs no tasks, so inspect
`--list-hosts` before execution.

## Workflow graph

Numbered playbooks are canonical. Roles contain reusable implementation;
unnumbered playbooks are compatibility wrappers.

The normal ESXi and guest workflow is:

```text
99-site-run.yml
  -> 99-esxi-site.yml
       -> validate inventory contract
       -> prove ESXi API access and gather facts
       -> 04-vm-power.yml (scope=all, powered-on)
  -> 99-guest-site.yml
       -> validate the managed SSH key pair
       -> enroll host keys and wait for SSH
       -> converge guest_base
       -> reconcile guest networking serially
```

The Kubernetes workflow is:

```text
99-kubernetes-site.yml
  -> prepare the control node
  -> power managed VMs
  -> reconcile guests
  -> prepare Kubernetes nodes
  -> 09-kubespray-deploy.yml
       -> render Kubespray inventory
       -> run deployment only with its enable flag
```

The complete platform workflow extends that base-cluster workflow:

```text
99-platform-site.yml
  -> 99-kubernetes-site.yml
  -> install MetalLB and its address pools
  -> prepare Longhorn nodes
  -> validate Kubernetes health
  -> 19-argocd-bootstrap.yml
       -> install pinned Argo CD v3 only when absent
       -> create AppProjects and root-applications only when absent
       -> hand continuous reconciliation to GitOps
```

MetalLB address pools and final health validation remain explicit follow-up
steps only after `99-kubernetes-site.yml`. The complete
`99-platform-site.yml` workflow composes both steps before Argo CD bootstrap.
Kubernetes reset, VM deletion, SSH recovery, and disk formatting are never part
of normal reconciliation.

The validation ladder adds guarantees progressively:

```text
00-validate.yml
  inventory variables and ownership are internally consistent
      -> 01-esxi-facts.yml
         ESXi API connectivity, credentials, and TLS behavior work
          -> 03-vm-validate-managed.yml
             every owned VM exists on the assigned ESXi host
              -> managed_vms ping / guest check mode
                 SSH and proposed guest convergence work
                  -> 14-kubernetes-health.yml
                     cluster services satisfy platform checks
```

`00-validate.yml` validates the committed ESXi variables and the managed-VM
ownership contract. It does not contact guest SSH services, prove that every VM
exists, render Kubespray input, or validate live Kubernetes health; those
guarantees belong to the later steps shown above.

## Preflight process

Before any playbook, prove scope and intent:

```bash
PLAYBOOK=playbooks/00-validate.yml

ansible-config dump --only-changed
ansible-inventory --graph
ansible-playbook "$PLAYBOOK" --syntax-check
ansible-playbook "$PLAYBOOK" --list-hosts
ansible-playbook "$PLAYBOOK" --list-tasks
ansible-playbook "$PLAYBOOK" --list-tags
```

For state changes, preview the smallest useful scope:

```bash
ansible-playbook playbooks/99-guest-site.yml \
  --check --diff --limit ubuntu_24.04-wrk-01
```

For VM lifecycle work, evaluate ownership and preview the explicit target:

```bash
ansible managed_vm_esxi \
  -m ansible.builtin.debug \
  -a 'var=esxi_managed_vm_names'

ansible-playbook playbooks/04-vm-power.yml \
  --check \
  -e vm_power_name=ubuntu_24.04-wrk-01 \
  -e vm_power_state=powered-on
```

Stop if host selection, ownership, extra variables, proposed changes, or safety
confirmations differ from the maintenance intent.

Use the execution modes deliberately:

| Mode | What it proves | What it does not prove |
|---|---|---|
| `--syntax-check` | YAML and Ansible parsing for the selected playbook | Inventory values, connectivity, or runtime behavior |
| `--list-hosts`, `--list-tasks`, `--list-tags` | Static play scope and available task selection | That conditional or looped tasks will execute |
| `--check --diff` | Supported modules' predicted changes | External command/API effects or complete postconditions |
| Normal execution | Applies the requested workflow and its assertions | Safety outside the selected hosts and supplied extra variables |

## Check mode and idempotence

Check mode is a prediction, not a transaction. Commands, external APIs, network
changes, and a state that a skipped task would have created cannot always be
simulated.

Project-specific rules are:

- inventory assertions stay active;
- unreliable key-fingerprint commands are omitted in check mode;
- NTP convergence waiting is skipped because preview mode does not enable NTP;
- live Netplan application and verification are skipped during preview;
- destructive workflows retain their safety assertions;
- Longhorn previews run read-only disk, kernel, and mount probes, retaining disk
  safety checks while deferring verification of newly created filesystems and
  mounts; installed-command and active-iSCSI checks wait for normal execution.

A second normal run should report no change unless live state drifted or a
command intentionally represents external orchestration. Use `changed_when`,
`failed_when`, and postcondition assertions to make exceptions explicit.

## Safety contracts

- VM deletion, Kubernetes reset, SSH recovery, and disk formatting require
  explicit opt-in values and dedicated entry points.
- Guest network changes run serially; validate one node before advancing.
- `kubernetes_primary_interface` is the per-host authority for guest networking,
  NIC-offload persistence, rendered kube-vip interface, and health validation.
- Vault files, `.vaultpass`, private keys, generated output, and local Packer
  values stay outside Git.
- `add_host` changes inventory only for the current run; discovered guests never
  replace durable production inventory.
- Registered results can represent `skipped` or check-mode execution. Consumers
  must not assume normal `stdout` exists.

## Modules and collection support

All module calls use fully qualified collection names, and every referenced
module resolves with the pinned runtime.

Support provenance matters:

- `ansible.builtin` ships with `ansible-core`;
- `ansible.posix` is separately released;
- `community.general` and `community.vmware` are community collections;
- `vmware.vmware` is separately released VMware content.

Official documentation does not imply identical vendor support for every
collection. Before upgrading, check `requires_ansible`, changelogs, module
deprecations, and VMware SDK requirements, then pin and validate the result.

Use the installed documentation as the runtime authority:

```bash
ansible-doc ansible.builtin.assert
ansible-doc ansible.posix.authorized_key
ansible-doc community.vmware.vmware_host_facts
ansible-doc vmware.vmware.vm_powerstate
```

Official references:

- [Collection index](https://docs.ansible.com/ansible/latest/collections/index.html)
- [Builtin collection](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)
- [ansible.posix collection](https://docs.ansible.com/ansible/latest/collections/ansible/posix/index.html)
- [community.general collection](https://docs.ansible.com/ansible/latest/collections/community/general/index.html)
- [community.vmware collection](https://docs.ansible.com/ansible/latest/collections/community/vmware/index.html)
- [vmware.vmware collection](https://docs.ansible.com/ansible/latest/collections/vmware/vmware/index.html)

## Validation and extension

CI and local pre-commit checks use the pinned requirements and validate the
inventory, YAML, Ansible lint rules, and every playbook's syntax. CI also runs the
offline regression suite, with `just` installed for wrapper coverage. Run that
suite separately from pre-commit locally:

```bash
source .venv/vmware/bin/activate
ansible-galaxy collection install --requirement requirements.yml
python -m unittest discover -s tests -v
PATH="$PWD/.venv/vmware/bin:$PATH" \
  .venv/vmware/bin/pre-commit run --all-files
git diff --check
```

For a new host, group, role, or workflow:

1. Keep environment topology in inventory and reusable behavior in roles.
2. Keep playbooks thin: select scope, set entry-point controls, and compose roles.
3. Use fully qualified collection names and conservative defaults.
4. Assert required inputs and unsafe combinations before mutation.
5. Define check-mode and idempotence behavior deliberately.
6. Add an independent postcondition or health check.
7. Update the ownership and maintenance documentation.
8. Run repository validation and the smallest relevant live test.

Adding a managed VM also requires functional group membership, `ansible_host`,
the primary interface, host-specific variables, and exactly one ESXi ownership
entry. Validate in this order: inventory, ownership, ESXi existence, SSH,
rendered Kubespray inventory, then cluster health.

## Official conceptual references

- [Inventory](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html)
- [Host patterns](https://docs.ansible.com/ansible/latest/inventory_guide/intro_patterns.html)
- [Variables](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html)
- [Precedence rules](https://docs.ansible.com/ansible/latest/reference_appendices/general_precedence.html)
- [Playbook reuse](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_reuse.html)
- [Conditionals](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_conditionals.html)
- [Check mode and diff mode](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_checkmode.html)
- [Tags](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_tags.html)
- [Privilege escalation](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_privilege_escalation.html)
- [Ansible Vault](https://docs.ansible.com/ansible/latest/vault_guide/index.html)
