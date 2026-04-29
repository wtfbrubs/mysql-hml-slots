resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  cidr_block     = var.vcn_cidr
  display_name   = "${local.prefix}-vcn"
  dns_label      = replace(local.prefix, "-", "")
  freeform_tags  = local.common_tags
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${local.prefix}-igw"
  enabled        = true
  freeform_tags  = local.common_tags
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${local.prefix}-rt-public"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.main.id
  }

  freeform_tags = local.common_tags
}

resource "oci_core_subnet" "public" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.main.id
  cidr_block        = cidrsubnet(var.vcn_cidr, 4, 0)
  display_name      = "${local.prefix}-subnet-public"
  dns_label         = "public"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.hml_host.id]
  freeform_tags     = local.common_tags
}

resource "oci_core_subnet" "private" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.main.id
  cidr_block                 = cidrsubnet(var.vcn_cidr, 4, 1)
  display_name               = "${local.prefix}-subnet-private"
  dns_label                  = "private"
  prohibit_public_ip_on_vnic = true
  security_list_ids          = [oci_core_security_list.mysql.id]
  freeform_tags              = local.common_tags
}

# Security list — Compute HML host
resource "oci_core_security_list" "hml_host" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${local.prefix}-sl-hml-host"

  ingress_security_rules {
    description = "SSH"
    protocol    = "6"
    source      = var.allowed_cidr
    tcp_options { min = 22; max = 22 }
  }

  ingress_security_rules {
    description = "MySQL slots"
    protocol    = "6"
    source      = var.allowed_cidr
    tcp_options { min = 3310; max = 3410 }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }

  freeform_tags = local.common_tags
}

# Security list — HeatWave MySQL (acessível apenas pelo host HML)
resource "oci_core_security_list" "mysql" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${local.prefix}-sl-mysql"

  ingress_security_rules {
    description = "MySQL do HML host"
    protocol    = "6"
    source      = cidrsubnet(var.vcn_cidr, 4, 0)
    tcp_options { min = 3306; max = 3306 }
  }

  freeform_tags = local.common_tags
}
