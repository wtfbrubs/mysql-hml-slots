resource "aws_db_subnet_group" "prd" {
  name       = "${local.prefix}-prd"
  subnet_ids = aws_subnet.private[*].id
  tags       = merge(local.common_tags, { Name = "${local.prefix}-db-subnet-group" })
}

resource "aws_db_parameter_group" "prd" {
  name   = "${local.prefix}-prd-params"
  family = "mysql8.0"

  parameter {
    name  = "binlog_format"
    value = "ROW"
  }

  parameter {
    name         = "log_bin_trust_function_creators"
    value        = "1"
    apply_method = "immediate"
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-prd-params" })
}

resource "aws_db_instance" "prd" {
  identifier        = "${local.prefix}-prd"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.prd.name
  vpc_security_group_ids = [aws_security_group.rds_prd.id]
  parameter_group_name   = aws_db_parameter_group.prd.name

  multi_az            = false
  publicly_accessible = false

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"

  # Altere para true antes de ir para produção real
  skip_final_snapshot = true
  deletion_protection = false

  tags = merge(local.common_tags, { Name = "${local.prefix}-prd", Role = "source" })
}
