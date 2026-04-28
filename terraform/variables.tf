variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "mysql-hml-slots"
}

variable "environment" {
  type    = string
  default = "hml"
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "allowed_cidr" {
  type        = string
  description = "Seu IP em CIDR para acesso SSH e slots (ex: 203.0.113.10/32)"
}

# RDS PRD
variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_name" {
  type    = string
  default = "appdb"
}

variable "db_username" {
  type    = string
  default = "admin"
}

variable "db_password" {
  type      = string
  sensitive = true
}

# EC2 HML host
variable "ec2_instance_type" {
  type    = string
  default = "t3.small"
}

variable "ec2_key_name" {
  type        = string
  description = "Nome de um EC2 Key Pair existente para acesso SSH de emergência"
}

variable "repo_url" {
  type        = string
  description = "URL git deste repositório para clone no host HML"
}

variable "hml_mysql_root_password" {
  type      = string
  sensitive = true
  default   = "hml-root-secret"
}
