# Just command reference

Run `just` or `just --list` to list recipes. Commands run from the repository root
and use the project virtual environment. `*args` means optional arguments forwarded
to the underlying command, preserving quoting and failure status. Parameter names are placeholders; do not
type the `$` markers displayed by `just` (they indicate exported parameters).

## Recipe mapping

| Recipe and arguments | Playbook or behavior |
|---|---|
| `default` | Show available project commands. |
| `bootstrap` | Install system Python 3.12 using sudo; Ubuntu 22.04 adds the Deadsnakes PPA. |
| `deps $python="python3.12"` | Install Packer, pinned Python tools, and Ansible collections. |
| `packer-install` | Install checksum-verified Packer 1.16.1 locally (no sudo required). |
| `secrets-init` | Copy local inventory and Packer examples without replacing existing files. |
| `vaultpass` | Create .vaultpass using a hidden, confirmed prompt; preserve an existing file. |
| `secrets-encrypt` | Encrypt local inventory secrets after editing placeholders; skip encrypted files. |
| `control-node *args` | [`00-control-node.yml`](../playbooks/00-control-node.yml) |
| `syntax *args` | [`99-site-run.yml`](../playbooks/99-site-run.yml) |
| `validate *args` | [`01-esxi-facts.yml`](../playbooks/01-esxi-facts.yml), [`99-site-run.yml`](../playbooks/99-site-run.yml) |
| `packer-validate target *args` | Validate Packer inputs for esxi-6.7 or esxi-8 without creating VMs. |
| `packer-build target *args` | Build selected VM files, or all target files if omitted; --force can destroy existing VMs. |
| `vm-power-states` | Show inventory-defined allowed power states without changing VM power. |
| `vm-power $vm $state *args` | [`04-vm-power.yml`](../playbooks/04-vm-power.yml) |
| `vm-power-all $state *args` | [`04-vm-power.yml`](../playbooks/04-vm-power.yml) |
| `vm-delete $vm $confirm *args` | [`05-vm-delete.yml`](../playbooks/05-vm-delete.yml) |
| `esxi-validate *args` | [`00-validate.yml`](../playbooks/00-validate.yml) |
| `esxi-facts *args` | [`01-esxi-facts.yml`](../playbooks/01-esxi-facts.yml) |
| `vm-list *args` | [`02-vm-list.yml`](../playbooks/02-vm-list.yml) |
| `vm-validate *args` | [`03-vm-validate-managed.yml`](../playbooks/03-vm-validate-managed.yml) |
| `guest-bootstrap *args` | [`06-guest-bootstrap.yml`](../playbooks/06-guest-bootstrap.yml) |
| `guest-network *args` | [`11-guest-network.yml`](../playbooks/11-guest-network.yml) |
| `guest-prepare *args` | [`99-guest-site.yml`](../playbooks/99-guest-site.yml) |
| `kubernetes-inventory *args` | [`07-kubespray-inventory.yml`](../playbooks/07-kubespray-inventory.yml) |
| `kubernetes-install *args` | [`08-kubespray-install.yml`](../playbooks/08-kubespray-install.yml) |
| `kubernetes-prepare *args` | [`10-kubernetes-node-prepare.yml`](../playbooks/10-kubernetes-node-prepare.yml) |
| `kubernetes-deploy *args` | [`09-kubespray-deploy.yml`](../playbooks/09-kubespray-deploy.yml) |
| `kubernetes-metallb *args` | [`13-kubespray-metallb.yml`](../playbooks/13-kubespray-metallb.yml) |
| `kubernetes-health *args` | [`14-kubernetes-health.yml`](../playbooks/14-kubernetes-health.yml) |
| `longhorn-prepare *args` | [`16-longhorn-node-prepare.yml`](../playbooks/16-longhorn-node-prepare.yml) |
| `argocd-bootstrap *args` | [`19-argocd-bootstrap.yml`](../playbooks/19-argocd-bootstrap.yml) |
| `kubernetes-client-setup source source_dir *args` | Fetch client artifacts from a trusted SSH source; preserve existing files. No deployment. |

## Scope and prerequisites

- `esxi-validate`, `esxi-facts`, and `vm-list` select `vmware_esxi` hosts;
  `vm-validate`, `vm-power`, and `vm-delete` select `managed_vm_esxi` hosts.
  Their `--limit` is an ESXi inventory host, not a guest name.
- `guest-bootstrap`, `guest-network`, and `guest-prepare` select `managed_vms`.
  Use a guest inventory name with `--limit`. Base configuration requires SSH and
  privilege escalation; full preparation also handles authentication validation,
  known hosts, waiting for SSH, and networking. It does not power on VMs.
- `vm-power VM STATE` and `vm-delete VM CONFIRMATION` fix single-VM scope and
  target arguments. Deletion requires the exact VM name twice. See
  [force deletion](../README.md#vm-deletion-shortcut); no `--force` alias exists.
- `syntax` checks `99-site-run.yml`, not every standalone playbook. `validate`
  adds host selection and live ESXi facts; `esxi-validate` only validates inventory
  configuration. Full repository checks remain `pre-commit run --all-files`.
- See [platform targets and guards](feature-maintenance.md#platform-shortcuts)
  before deployment. These wrappers do not automatically enable deployment,
  formatting, or Argo CD bootstrap. The MetalLB playbook itself enables its
  tagged deployment and applies address pools. Check mode has workflow-specific limits.
- Packer recipes take a target, followed by options or explicit VM variable files.
  Without file selection, every target file is built in sorted order. Existing
  VMs are not skipped. `--force` may destroy them; `--start-at` only filters the
  selected file list. See [build examples](../README.md#shortcuts-with-just-ubuntu-2404-control-node).
- `kubernetes-client-setup` accepts its own `--cluster` and `--identity` options,
  not Ansible options. See [client restoration](feature-maintenance.md#health-checks-from-another-checkout-or-control-node).

## Explicit playbook workflows

Not every playbook has a shortcut. The following remain explicit invocations of
`.venv/vmware/bin/ansible-playbook playbooks/FILE.yml` with the workflow's required
variables. This keeps their additional effects visible:

| Playbook | Purpose / prerequisite |
|---|---|
| `12-guest-ssh-recover.yml` | Recover SSH access through VMware Tools; use the recovery procedure. |
| `15-kubespray-reset.yml` | Destructive Kubernetes reset; use the reset procedure and existing confirmations. |
| `17-ssh-key-rotate.yml` | Rotate keys with explicit deploy/revoke phase and validated key files. |
| `18-project-sync.yml` | Copy project files to an explicit managed `target_host`. |
| `99-esxi-site.yml` | Validate ESXi, gather facts, and power on all managed VMs. |
| `99-guest-discover.yml` | Power on selected VMs, discover IPs, and bootstrap with a credential source. |
| `99-kubernetes-site.yml` | Prepare the control node, power on VMs, prepare guests, and deploy Kubernetes. |
| `99-platform-site.yml` | Run the Kubernetes workflow, MetalLB, storage preparation, health, and Argo CD. |
| `99-site-run.yml` | Compose ESXi power-on and full guest reconciliation. |

Legacy alias playbooks (`site-esxi.yml`, `site-guest.yml`, `rotate-ssh-key.yml`,
`sync-project.yml`) do not need duplicate recipes. See the
[maintenance guide](feature-maintenance.md) before running advanced workflows.
