from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


class AuthException(BaseException):
    """
    Custom exception class for authentication-related errors

    Inherits from BaseException but fixes error_group to 'auth'
    """

    def __init__(
        self,
        status_code: int = 401,
        error_name: str = "auth_error",
        error_msg: str = "An authentication error occurred",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="auth",  # Fixed to 'auth' for all AuthExceptions
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class AuthError:
    """
    Class containing all authentication error types as constants.
    This allows referencing error types using dot notation (AuthError.INVALID_CREDENTIALS)
    """

    PHONE_ALREADY_REGISTERED = "phone_already_registered"
    USERNAME_ALREADY_TAKEN = "username_already_taken"
    INVALID_VERIFICATION_CODE = "invalid_verification_code"
    USER_NOT_FOUND = "user_not_found"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_REFRESH_TOKEN = "invalid_refresh_token"
    EXPIRED_TOKEN = "expired_token"
    # New error types for auth.py
    INACTIVE_USER = "inactive_user"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    INVALID_TOKEN = "invalid_token"
    TOKEN_VALIDATION_ERROR = "token_validation_error"
