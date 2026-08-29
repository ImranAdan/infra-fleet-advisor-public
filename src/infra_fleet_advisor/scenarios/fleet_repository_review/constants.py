TAXONOMY = frozenset(
    {"security", "reliability", "cost", "lifecycle", "maintainability", "gitops_correctness"}
)

EVIDENCE_KIND_CREDENTIAL_METHOD = "gha_credential_method"
EVIDENCE_KIND_TRIVY_GATE = "gha_trivy_gate"
EVIDENCE_KIND_IAM_WILDCARD = "tf_iam_wildcard"

GHA_COLLECTOR_ID = "github_actions_workflow_collector"
GHA_COLLECTOR_VERSION = "1.1.0"

TF_IAM_COLLECTOR_ID = "terraform_iam_collector"
TF_IAM_COLLECTOR_VERSION = "1.1.0"
