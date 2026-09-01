#cloud-config
autoinstall:
  version: 1
  interactive-sections: []
  locale: en_US.UTF-8
  refresh-installer:
    update: false
  keyboard:
    layout: us
    variant: ""
  source:
    id: ubuntu-server-minimal
  network:
    version: 2
    ethernets:
      any:
        match:
          name: "e*"
        dhcp4: true
  storage:
    layout:
      name: lvm
      sizing-policy: all
  identity:
    hostname: ${hostname}
    username: ${username}
    password: "${password_hash}"
  ssh:
    install-server: true
    allow-pw: true
%{ if ssh_authorized_key != "" ~}
    authorized-keys:
      - ${ssh_authorized_key}
%{ endif ~}
  packages:
    - open-vm-tools
    - curl
    - git
  updates: security
