output "hml_host_public_ip" {
  description = "IP público do host HML"
  value       = aws_eip.hml_host.public_ip
}

output "hml_host_ssh" {
  description = "Comando SSH para o host HML"
  value       = "ssh ec2-user@${aws_eip.hml_host.public_ip}"
}

output "hml_instance_id" {
  description = "ID da instância EC2 HML (usar como HML_INSTANCE_ID no GitHub)"
  value       = aws_instance.hml_host.id
}

output "rds_prd_endpoint" {
  description = "Endpoint do RDS PRD"
  value       = aws_db_instance.prd.address
}

output "github_actions_access_key_id" {
  description = "AWS_ACCESS_KEY_ID para o GitHub Actions (adicionar como secret)"
  value       = aws_iam_access_key.github_actions.id
}

output "github_actions_secret_access_key" {
  description = "AWS_SECRET_ACCESS_KEY para o GitHub Actions (adicionar como secret)"
  value       = aws_iam_access_key.github_actions.secret
  sensitive   = true
}
