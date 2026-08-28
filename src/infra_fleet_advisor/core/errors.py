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


class SynthesisError(AdvisorError):
    """Synthesis could not complete. Never degraded to an empty result: an
    empty synthesis would mark every prior finding resolved."""
