packer {
  required_plugins {
    vsphere = {
      source  = "github.com/vmware/vsphere"
      version = ">= 2.1.2"
    }
  }
}

variable "esxi_hostname" {
  type = string
}

variable "esxi_username" {
  type = string
}

variable "esxi_password" {
  type      = string
  sensitive = true
}

variable "esxi_insecure_connection" {
  type    = bool
  default = true
}

variable "esxi_datacenter" {
  type    = string
  default = "ha-datacenter"
}

variable "esxi_datastore" {
  type    = string
  default = "RAID5-DATA"
}

variable "esxi_iso_datastore" {
  type    = string
  default = "RAID1-OS"
}

variable "esxi_iso_directory" {
  type    = string
  default = "iso"
}

variable "ubuntu_iso_name" {
  type    = string
  default = "ubuntu-24.04.4-live-server-amd64.iso"
}

variable "vm_name" {
  type    = string
  default = "ubuntu_24.04-mgmt-01"
}

variable "guest_hostname" {
  type    = string
  default = ""
}

variable "vm_network" {
  type    = string
  default = "VM Network"
}

variable "vm_resource_pool" {
  type    = string
  default = "Resources"
}

variable "vm_firmware" {
  type    = string
  default = "efi"
}

variable "vm_cpu" {
  type    = number
  default = 2
}

variable "vm_memory_mb" {
  type    = number
  default = 2048
}

variable "vm_disk_mb" {
  type    = number
  default = 40960
}

variable "ssh_username" {
  type    = string
  default = "sysadmin"
}

variable "ssh_password" {
  type      = string
  sensitive = true
}

variable "ssh_password_hash" {
  type      = string
  sensitive = true
}

variable "ssh_authorized_key" {
  type    = string
  default = ""
}

variable "ip_settle_timeout" {
  type    = string
  default = "2m"
}

variable "boot_wait" {
  type    = string
  default = "15s"
}

variable "boot_keygroup_interval" {
  type    = string
  default = "100ms"
}

variable "ssh_timeout" {
  type    = string
  default = "75m"
}

locals {
  iso_path           = "[${var.esxi_iso_datastore}] ${var.esxi_iso_directory}/${var.ubuntu_iso_name}"
  http_meta_data_tpl = abspath("${path.root}/http/meta-data.pkrtpl.hcl")
  http_user_data_tpl = abspath("${path.root}/http/user-data.pkrtpl.hcl")
  guest_hostname     = var.guest_hostname != "" ? var.guest_hostname : replace(replace(var.vm_name, "_", "-"), ".", "-")
}

source "vsphere-iso" "ubuntu_24_04" {
  vcenter_server      = var.esxi_hostname
  username            = var.esxi_username
  password            = var.esxi_password
  insecure_connection = var.esxi_insecure_connection

  datacenter    = var.esxi_datacenter
  host          = var.esxi_hostname
  datastore     = var.esxi_datastore
  resource_pool = var.vm_resource_pool

  vm_name       = var.vm_name
  guest_os_type = "ubuntu64Guest"
  firmware      = var.vm_firmware
  CPUs          = var.vm_cpu
  RAM           = var.vm_memory_mb
  RAM_hot_plug  = true
  CPU_hot_plug  = true

  disk_controller_type = ["pvscsi"]
  storage {
    disk_size             = var.vm_disk_mb
    disk_thin_provisioned = true
  }

  network_adapters {
    network      = var.vm_network
    network_card = "vmxnet3"
  }

  iso_paths              = [local.iso_path]
  boot_order             = "cdrom,disk"
  boot_wait              = var.boot_wait
  boot_keygroup_interval = var.boot_keygroup_interval

  ip_settle_timeout = var.ip_settle_timeout

  http_content = {
    "/meta-data" = templatefile(local.http_meta_data_tpl, {
      hostname = local.guest_hostname
    })
    "/user-data" = templatefile(local.http_user_data_tpl, {
      hostname           = local.guest_hostname
      username           = var.ssh_username
      password_hash      = var.ssh_password_hash
      ssh_authorized_key = var.ssh_authorized_key
    })
  }

  boot_command = [
    "<wait><esc><wait>",
    "e<wait>",
    "<down><down><down><end>",
    " autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ ---",
    "<f10>"
  ]

  ssh_username = var.ssh_username
  ssh_password = var.ssh_password
  ssh_timeout  = var.ssh_timeout

  shutdown_command = "echo '${var.ssh_password}' | sudo -S shutdown -P now"
  remove_cdrom     = true
}

build {
  sources = ["source.vsphere-iso.ubuntu_24_04"]

  provisioner "shell" {
    execute_command = "echo '${var.ssh_password}' | sudo -S -E sh -c '{{ .Vars }} {{ .Path }}'"
    inline = [
      "apt-get update",
      "apt-get install -y open-vm-tools curl git",
      "systemctl enable --now open-vm-tools",
      "cloud-init clean --logs"
    ]
  }
}
