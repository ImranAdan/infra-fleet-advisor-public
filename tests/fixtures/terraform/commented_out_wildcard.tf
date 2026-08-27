/*
resource "aws_iam_policy" "retired" {
  name = "RetiredPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["eks:*"]
        Resource = "*"
      },
    ]
  })
}
*/

resource "aws_iam_policy" "active" {
  name = "ActivePolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::example-bucket/*"
      },
    ]
  })
}
