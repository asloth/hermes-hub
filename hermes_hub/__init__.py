"""hermes-hub: one terminal front-end for Hermes profiles and peers."""

__version__ = "0.1.0"


class HubError(Exception):
    """An expected failure. Reported as one line on stderr; never a traceback."""

    code = 1

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class UsageError(HubError):
    """Bad invocation: unknown target, missing argument, ambiguous name."""

    code = 2
