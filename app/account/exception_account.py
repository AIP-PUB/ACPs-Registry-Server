from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


class AccountException(BaseException):
    """
    Custom exception class for account-related errors

    Inherits from BaseException but fixes error_group to 'account'
    """

    def __init__(
        self,
        status_code: int = 400,
        error_name: str = "user_error",
        error_msg: str = "An error occurred with account operation",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="account",  # Fixed to 'account' for all UserExceptions
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class AccountError:
    """
    Class containing all account error types as constants.
    This allows referencing error types using dot notation (UserError.PHONE_ALREADY_REGISTERED)
    """

    # User management errors
    PHONE_ALREADY_REGISTERED = "phone_already_registered"
    USERNAME_ALREADY_TAKEN = "username_already_taken"
    USER_NOT_FOUND = "user_not_found"
    INCORRECT_PASSWORD = "incorrect_password"
    INVALID_VERIFICATION_CODE = "invalid_verification_code"
    ROLE_NOT_FOUND = "role_not_found"
    ROLES_NOT_FOUND = "roles_not_found"

    # Authentication errors
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_REFRESH_TOKEN = "invalid_refresh_token"
    EXPIRED_TOKEN = "expired_token"
    INVALID_REQUEST = "invalid_request"
    PASSWORD_COMPLEXITY_ERROR = "password_complexity_error"
