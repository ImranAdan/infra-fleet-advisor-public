resource "aws_iam_policy" "scoped_example" {
  name        = "ScopedExamplePolicy"
  description = "Narrowly scoped permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = [
          "arn:aws:s3:::terraform-state-*",
          "arn:aws:s3:::terraform-state-*/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/terraform-state-lock*"
      },
    ]
  })

  tags = {
    Name      = "scoped-example-policy"
    ManagedBy = "terraform"
  }
}
