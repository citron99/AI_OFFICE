class DomainError(Exception):
    """Base class for expected domain failures."""


class IdempotencyConflictError(DomainError):
    pass


class TaskNotFoundError(DomainError):
    pass


class InvalidStateTransitionError(DomainError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Task state cannot transition from {current} to {target}")
        self.current = current
        self.target = target


class ModelOutputInvalidError(DomainError):
    pass


class FileValidationError(DomainError):
    pass


class ArtifactNotFoundError(DomainError):
    pass


class RunBudgetExceededError(DomainError):
    """The server-owned process budget reached a hard stop line."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RetryableAgentError(DomainError):
    """A node failure the process author marked as retryable."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class NodeExecutionFailed(DomainError):
    """A node exhausted its retry policy: the run must stop in FAILED_SAFE."""

    def __init__(
        self,
        *,
        node_id: str,
        step_id: str,
        error_code: str,
        attempts: int,
    ) -> None:
        super().__init__(f"Node {node_id} failed after {attempts} attempts: {error_code}")
        self.node_id = node_id
        self.step_id = step_id
        self.error_code = error_code
        self.attempts = attempts


class GrantDeniedError(DomainError):
    """A step tried to use a data scope without a valid short-lived grant."""

    def __init__(self, scope: str, reason: str) -> None:
        super().__init__(f"Grant denied for scope {scope}: {reason}")
        self.scope = scope
        self.reason = reason
