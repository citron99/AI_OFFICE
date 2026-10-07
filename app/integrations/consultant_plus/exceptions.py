class ConsultantPlusUnavailableError(RuntimeError):
    """The licensed channel is unreachable: the legal route must stop."""


class LicenseScopeExceededError(RuntimeError):
    """A request would exceed the approved license scope; never attempt it."""
