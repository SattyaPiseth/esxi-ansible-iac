# Documentation

This directory contains maintenance and focused operational guidance for ESXi Ansible IaC.

Start with the [project README](../README.md) for installation and normal operation. Use the [feature maintenance guide](feature-maintenance.md) when changing configuration or implementation.

## Documentation map

| Topic | Operator workflow | Maintenance reference |
|---|---|---|
| Ansible architecture and execution | [Canonical playbooks](../README.md#canonical-playbooks) | [Ansible architecture and workflow](ansible-architecture-and-workflow.md) |
| Inventory and secrets | [First-time setup](../README.md#first-time-setup) | [Inventory and secrets](feature-maintenance.md#1-inventory-and-secrets) |
| Control node | [Install dependencies](../README.md#1-install-dependencies) | [Control-node dependencies](feature-maintenance.md#2-control-node-dependencies) |
| Ubuntu VM builds | [Build Ubuntu VMs](../README.md#build-ubuntu-vms) | [Packer maintenance](feature-maintenance.md#3-ubuntu-vm-creation-with-packer) |
| ESXi and VM lifecycle | [Canonical playbooks](../README.md#canonical-playbooks) | [ESXi and VM lifecycle](feature-maintenance.md#4-esxi-validation-and-vm-lifecycle) |
| Guest SSH/bootstrap | [Reconcile guests](../README.md#reconcile-guests) | [Guest access maintenance](feature-maintenance.md#5-guest-ssh-discovery-bootstrap-and-rotation) |
| Guest network/offloads | [Reconcile guests](../README.md#reconcile-guests) | [Network and offload maintenance](feature-maintenance.md#6-guest-networking-and-nic-offloads) |
| Kubernetes/Kubespray | [Deploy Kubernetes](../README.md#deploy-kubernetes) | [Kubespray lifecycle](feature-maintenance.md#7-kubernetes-inventory-and-kubespray-lifecycle) |
| kube-vip | [Deploy Kubernetes](../README.md#deploy-kubernetes) | [Feature ownership](feature-maintenance.md#8-kube-vip-control-plane-endpoint) and [detailed procedure](kube-vip-per-node-interface.md) |
| MetalLB/add-ons | [Deploy Kubernetes](../README.md#deploy-kubernetes) | [MetalLB and add-ons](feature-maintenance.md#9-metallb-and-cluster-add-ons) |
| Cluster health | [Troubleshooting](../README.md#troubleshooting) | [Health and kubeconfig](feature-maintenance.md#10-kubernetes-health-and-operator-kubeconfig) |
| Longhorn hosts | [Prepare Longhorn nodes](../README.md#prepare-longhorn-nodes) | [Longhorn preparation](feature-maintenance.md#11-longhorn-node-preparation) |
| Project synchronization | [Canonical playbooks](../README.md#canonical-playbooks) | [Project synchronization](feature-maintenance.md#12-project-synchronization) |
| CI and validation | [Development and CI](../README.md#development-and-ci) | [CI and quality](feature-maintenance.md#13-ci-and-repository-quality) |
| Change review | [Safety](../README.md#safety) | [Change checklist](feature-maintenance.md#change-checklist) |

## Document responsibilities

### Project README

Use [README.md](../README.md) for:

- project purpose and supported topology;
- first-time installation;
- normal operator workflows;
- canonical entry points;
- high-level safety and troubleshooting.

### Feature maintenance guide

Use [feature-maintenance.md](feature-maintenance.md) for:

- feature ownership and source-of-truth files;
- important variables and safety controls;
- configuration update procedures;
- feature-specific validation;
- maintenance risks and boundaries.

### Ansible architecture and workflow

Use [ansible-architecture-and-workflow.md](ansible-architecture-and-workflow.md) for:

- inventory selection, variable resolution, and host-scoped ownership;
- playbook/role composition and execution flow;
- preflight, check-mode, safety, and validation contracts;
- module provenance, collection support boundaries, and official references.

### kube-vip interface guide

Use [kube-vip-per-node-interface.md](kube-vip-per-node-interface.md) for:

- per-node interface selection;
- inventory-to-Kubespray data flow;
- safe reconciliation;
- live verification and failover requirements;
- troubleshooting and rollback.

## Documentation maintenance policy

When a configuration contract changes:

1. Update the implementation and inventory examples.
2. Update its feature section in the maintenance guide.
3. Update the root README only if the operator workflow changes.
4. Update a focused guide when its detailed procedure changes.
5. Add or repair cross-links instead of copying the same procedure.
6. Run relative-link validation and the repository pre-commit checks.

Generated files, runtime logs, credentials, and one-time incident notes do not belong in these documents.
