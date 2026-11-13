class AppError(Exception):
    """Safe application error; API maps it to HTTP, future workers record it directly."""

    def __init__(self, status_code: int, detail: str, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
