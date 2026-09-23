TAXONOMY = frozenset(
    {"security", "reliability", "cost", "lifecycle", "maintainability", "gitops_correctness"}
)

EVIDENCE_KIND_CREDENTIAL_METHOD = "gha_credential_method"
EVIDENCE_KIND_TRIVY_GATE = "gha_trivy_gate"
EVIDENCE_KIND_IAM_WILDCARD = "tf_iam_wildcard"
EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY = "k8s_deployment_rollout_capacity"
EVIDENCE_KIND_FLEET_LIFECYCLE = "fleet_profile_lifecycle"
EVIDENCE_KIND_CONTAINER_HARDENING = "k8s_container_hardening"
EVIDENCE_KIND_LOG_RETENTION = "tf_log_retention"
EVIDENCE_KIND_ECR_LIFECYCLE = "tf_ecr_lifecycle"

GHA_COLLECTOR_ID = "github_actions_workflow_collector"
GHA_COLLECTOR_VERSION = "1.3.0"

TF_IAM_COLLECTOR_ID = "terraform_iam_collector"
TF_IAM_COLLECTOR_VERSION = "1.4.0"

K8S_DEPLOYMENT_COLLECTOR_ID = "kubernetes_deployment_collector"
K8S_DEPLOYMENT_COLLECTOR_VERSION = "1.1.0"

FLEET_LIFECYCLE_COLLECTOR_ID = "fleet_lifecycle_collector"
FLEET_LIFECYCLE_COLLECTOR_VERSION = "1.2.0"

TF_COST_COLLECTOR_ID = "terraform_cost_collector"
TF_COST_COLLECTOR_VERSION = "1.0.0"
