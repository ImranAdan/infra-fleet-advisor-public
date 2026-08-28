resource "aws_iam_policy" "single_statement" {
  name = "SingleStatementPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = {
      Effect   = "Allow"
      Action   = ["eks:*"]
      Resource = "*"
    }
  })
}
