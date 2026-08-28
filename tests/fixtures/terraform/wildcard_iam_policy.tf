resource "aws_iam_role" "github_actions" {
  name = "GitHubActions-InfraFleet"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
      }
    ]
  })
}

resource "aws_iam_policy" "github_actions" {
  name        = "GitHubActions-InfraFleet-Policy"
  description = "Permissions for GitHub Actions to manage EKS infrastructure"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
        ]
        Resource = [
          "arn:aws:s3:::terraform-state-*",
          "arn:aws:s3:::terraform-state-*/*",
        ]
      },
      # STS (to get caller identity, useful for debugging)
      {
        Effect = "Allow"
        Action = [
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
    ]
  })

  tags = {
    Name        = "github-actions-policy"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}
