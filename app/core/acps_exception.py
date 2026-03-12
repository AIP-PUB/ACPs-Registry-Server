from typing import Any, Dict, Optional


class AcpsException(Exception):
    """Base exception for ACPs protocol-family APIs."""

    def __init__(
        self,
        *,
        protocol: str,
        code: int,
        message: str,
        http_status: int = 400,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.protocol = protocol
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data or None
        super().__init__(message)

    def to_response_payload(self) -> Dict[str, Any]:
        """Return payload that conforms to ATR CommonResponse error shape."""
        return {
            "status": "error",
            "error": {
                "code": self.code,
                "message": self.message,
                "data": self.data,
            },
        }
