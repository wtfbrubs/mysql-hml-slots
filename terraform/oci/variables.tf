# ── OCI credentials ──────────────────────────────────────────────────────────
variable "tenancy_ocid" { type = string }
variable "user_ocid"    { type = string }
variable "fingerprint"  { type = string }
variable "private_key_path" { type = string }
variable "region" {
  type    = string
  default = "sa-saopaulo-1"
}

# ── Project ───────────────────────────────────────────────────────────────────
variable "project_name" {
  type    = string
  default = "mysql-hml-slots"
}

variable "environment" {
  type    = string
  default = "hml"
}

variable "compartment_ocid" {
  type        = string
  description = "OCID do compartimento onde os recursos serão criados"
}

# ── Network ───────────────────────────────────────────────────────────────────
variable "vcn_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "allowed_cidr" {
  type        = string
  description = "Seu IP em CIDR para acesso SSH e slots (ex: 203.0.113.10/32)"
}

# ── Compute (host HML) ────────────────────────────────────────────────────────
variable "compute_shape" {
  type    = string
  default = "VM.Standard.E4.Flex"
}

variable "compute_ocpus" {
  type    = number
  default = 1
}

variable "compute_memory_gb" {
  type    = number
  default = 4
}

variable "ssh_public_key" {
  type        = string
  description = "Chave SSH pública para acesso de emergência à instância"
}

variable "repo_url" {
  type        = string
  description = "URL git deste repositório para clone na instância"
}

variable "hml_mysql_root_password" {
  type      = string
  sensitive = true
  default   = "hml-root-secret"
}

# ── MySQL HeatWave (PRD) ──────────────────────────────────────────────────────
variable "mysql_shape" {
  type    = string
  default = "MySQL.VM.Standard.E4.1.8GB"
}

variable "mysql_admin_user" {
  type    = string
  default = "admin"
}

variable "mysql_admin_password" {
  type      = string
  sensitive = true
}

variable "mysql_db_name" {
  type    = string
  default = "appdb"
}
