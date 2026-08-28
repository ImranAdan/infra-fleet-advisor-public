resource "aws_iam_policy" "broken" {
  name = "BrokenPolicy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [ this is not valid JSON at all : : :
