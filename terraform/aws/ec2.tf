data "aws_ami" "amazon_linux_2" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

# IAM role para o EC2 — permite SSM (sem necessidade de abrir porta 22 para CI/CD)
resource "aws_iam_role" "ec2_hml" {
  name = "${local.prefix}-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2_hml.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_hml" {
  name = "${local.prefix}-ec2-profile"
  role = aws_iam_role.ec2_hml.name
}

resource "aws_instance" "hml_host" {
  ami                    = data.aws_ami.amazon_linux_2.id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.ec2_hml.id]
  key_name               = var.ec2_key_name
  iam_instance_profile   = aws_iam_instance_profile.ec2_hml.name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    repo_url                = var.repo_url
    hml_mysql_root_password = var.hml_mysql_root_password
    prd_host                = aws_db_instance.prd.address
    prd_port                = aws_db_instance.prd.port
    prd_user                = var.db_username
    prd_password            = var.db_password
    mysql_version           = "8.0"
    slots_base_port         = 3310
  })

  tags = merge(local.common_tags, { Name = "${local.prefix}-host", Role = "hml-host" })
}

resource "aws_eip" "hml_host" {
  instance = aws_instance.hml_host.id
  domain   = "vpc"
  tags     = merge(local.common_tags, { Name = "${local.prefix}-eip" })
}
