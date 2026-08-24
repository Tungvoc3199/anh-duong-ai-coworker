from __future__ import annotations


class OpenClawTransportError(RuntimeError):
    """Raised when the OpenClaw transport fails or returns an error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        uncertain_side_effect: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.uncertain_side_effect = uncertain_side_effect
