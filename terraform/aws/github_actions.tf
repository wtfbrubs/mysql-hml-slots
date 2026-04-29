# IAM user para o GitHub Actions executar comandos no EC2 via SSM
resource "aws_iam_user" "github_actions" {
  name = "${local.prefix}-github-actions"
  tags = local.common_tags
}

resource "aws_iam_user_policy" "github_actions_ssm" {
  name = "ssm-hml-host"
  user = aws_iam_user.github_actions.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMSendCommand"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations",
          "ssm:DescribeInstanceInformation"
        ]
        Resource = [
          "arn:aws:ec2:${var.aws_region}:*:instance/${aws_instance.hml_host.id}",
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"
        ]
      }
    ]
  })
}

resource "aws_iam_access_key" "github_actions" {
  user = aws_iam_user.github_actions.name
}
