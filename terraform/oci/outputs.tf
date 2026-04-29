output "hml_host_public_ip" {
  description = "IP público do host HML"
  value       = oci_core_instance.hml_host.public_ip
}

output "hml_host_ssh" {
  description = "Comando SSH para o host HML"
  value       = "ssh opc@${oci_core_instance.hml_host.public_ip}"
}

output "mysql_prd_endpoint" {
  description = "Endpoint do HeatWave MySQL PRD"
  value       = oci_mysql_mysql_db_system.prd.endpoints[0].hostname
}

output "mysql_prd_port" {
  description = "Porta do HeatWave MySQL PRD"
  value       = oci_mysql_mysql_db_system.prd.endpoints[0].port
}
