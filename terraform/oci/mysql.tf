resource "oci_mysql_mysql_db_system" "prd" {
  compartment_id      = var.compartment_ocid
  display_name        = "${local.prefix}-prd"
  shape_name          = var.mysql_shape
  subnet_id           = oci_core_subnet.private.id
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name

  admin_username = var.mysql_admin_user
  admin_password = var.mysql_admin_password

  data_storage_size_in_gb = 50

  # Binlog obrigatório para replicação PRD → base
  configuration_id = oci_mysql_mysql_configuration.prd.id

  backup_policy {
    is_enabled        = true
    retention_in_days = 7
    window_start_time = "03:00"
  }

  deletion_policy {
    automatic_backup_retention = "RETAIN"
    final_backup               = "REQUIRE_FINAL_BACKUP"
    is_delete_protected        = true
  }

  freeform_tags = local.common_tags
}

resource "oci_mysql_mysql_configuration" "prd" {
  compartment_id = var.compartment_ocid
  shape_name     = var.mysql_shape
  display_name   = "${local.prefix}-prd-config"

  variables {
    binlog_row_image      = "FULL"
    binlog_expire_logs_seconds = 604800
    gtid_mode             = "ON"
    enforce_gtid_consistency = "ON"
  }

  freeform_tags = local.common_tags
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}
