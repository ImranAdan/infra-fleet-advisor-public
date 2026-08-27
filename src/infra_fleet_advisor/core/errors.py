class AdvisorError(Exception):
    pass


class PolicyError(AdvisorError):
    pass


class ProvenanceError(AdvisorError):
    pass


class UnsafePathError(AdvisorError):
    pass


class BoundedExecutionExceeded(AdvisorError):
    pass
