from typing import Optional, Dict, Any


class BaseException(Exception):
    """
    Custom exception class for application-specific errors

    Attributes:
        status_code: HTTP status code to return
        error_group: The functional group where error occurred
        error_name: Specific error name
        error_msg: Human-readable error description
        input_params: Parameters that caused the error
    """

    def __init__(
        self,
        status_code: int = 400,
        error_group: str = "base",
        error_name: str = "unknown_error",
        error_msg: str = "An error occurred",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.error_group = error_group
        self.error_name = error_name
        self.error_msg = error_msg
        self.input_params = input_params or {}
        super().__init__(self.error_msg)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to a dictionary for JSON response"""
        return {
            "status_code": self.status_code,
            "error_group": self.error_group,
            "error_name": self.error_name,
            "error_msg": self.error_msg,
            "input_params": self.input_params,
        }
