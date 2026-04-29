data "oci_core_images" "oracle_linux" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = "8"
  shape                    = var.compute_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_instance" "hml_host" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = "${local.prefix}-host"
  shape               = var.compute_shape

  shape_config {
    ocpus         = var.compute_ocpus
    memory_in_gbs = var.compute_memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.oracle_linux.images[0].id
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(templatefile("${path.module}/templates/user_data.sh.tftpl", {
      repo_url                = var.repo_url
      hml_mysql_root_password = var.hml_mysql_root_password
      prd_host                = oci_mysql_mysql_db_system.prd.endpoints[0].hostname
      prd_port                = 3306
      prd_user                = var.mysql_admin_user
      prd_password            = var.mysql_admin_password
      mysql_version           = "8.0"
      slots_base_port         = 3310
    }))
  }

  freeform_tags = local.common_tags
}
