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
EVIDENCE_KIND_COST_TAGS = "tf_cost_allocation_tags"
EVIDENCE_KIND_INGRESS_RESTRICTION = "k8s_ingress_restriction"
EVIDENCE_KIND_EGRESS_ACCEPTANCE = "k8s_egress_acceptance"
EVIDENCE_KIND_INGRESS_HTTPS = "k8s_ingress_https"
EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE = "k8s_token_privilege"
EVIDENCE_KIND_WORKER_SCALING = "tf_worker_scaling"
EVIDENCE_KIND_EKS_ENDPOINT = "tf_eks_endpoint_exposure"
EVIDENCE_KIND_IDLE_CAPACITY = "tf_idle_capacity_schedule"
EVIDENCE_KIND_SESSION_COOKIE = "app_session_cookie"
EVIDENCE_KIND_DEPENDENCY_UPDATES = "dependency_update_coverage"
EVIDENCE_KIND_ECR_PUBLICATION_GATE = "gha_ecr_publication_gate"
EVIDENCE_KIND_APPLICATION_COUPLING = "platform_application_coupling"

GHA_COLLECTOR_ID = "github_actions_workflow_collector"
GHA_COLLECTOR_VERSION = "1.5.0"

TF_IAM_COLLECTOR_ID = "terraform_iam_collector"
TF_IAM_COLLECTOR_VERSION = "1.4.0"

K8S_DEPLOYMENT_COLLECTOR_ID = "kubernetes_deployment_collector"
K8S_DEPLOYMENT_COLLECTOR_VERSION = "2.0.0"

FLEET_LIFECYCLE_COLLECTOR_ID = "fleet_lifecycle_collector"
FLEET_LIFECYCLE_COLLECTOR_VERSION = "1.4.0"

TF_COST_COLLECTOR_ID = "terraform_cost_collector"
TF_COST_COLLECTOR_VERSION = "1.4.0"

DEPENDENCY_UPDATE_COLLECTOR_ID = "dependency_update_collector"
DEPENDENCY_UPDATE_COLLECTOR_VERSION = "1.0.0"

K8S_SECURITY_COLLECTOR_ID = "kubernetes_security_collector"
K8S_SECURITY_COLLECTOR_VERSION = "2.0.0"

APP_CONFIG_COLLECTOR_ID = "application_config_collector"
APP_CONFIG_COLLECTOR_VERSION = "1.0.0"

APP_CONTRACT_COLLECTOR_ID = "application_contract_collector"
APP_CONTRACT_COLLECTOR_VERSION = "1.1.0"
