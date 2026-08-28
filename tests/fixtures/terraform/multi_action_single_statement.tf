resource "aws_iam_policy" "multi_action" {
  name = "MultiActionPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:*",
          "ec2:*",
        ]
        Resource = "*"
      },
    ]
  })
}
