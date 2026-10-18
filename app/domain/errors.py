class DomainError(Exception):
    """A business refusal whose message is written in Spanish for the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
