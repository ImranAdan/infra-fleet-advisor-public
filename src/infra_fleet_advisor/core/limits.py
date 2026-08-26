from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Hard bounds enforced across the run — never derived from repository
    content, only from policy and fixed defaults."""

    max_wall_seconds: int
    max_model_calls: int
    max_workflow_files: int
    max_file_bytes: int
    max_recommendations: int
