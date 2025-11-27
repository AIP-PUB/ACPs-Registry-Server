from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


class FileException(BaseException):
    """
    Custom exception class for file-related errors

    Inherits from BaseException but fixes error_group to 'file'
    """

    def __init__(
        self,
        status_code: int = 400,
        error_name: str = "file_error",
        error_msg: str = "An error occurred with file operation",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="file",  # Fixed to 'file' for all FileExceptions
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class FileError:
    """
    Class containing all file error types as constants.
    This allows referencing error types using dot notation (FileError.FILE_NOT_FOUND)
    """

    FILE_UPLOAD_FAILED = "file_upload_failed"
    FILE_DELETE_FAILED = "file_delete_failed"
    FILE_CLEANUP_FAILED = "file_cleanup_failed"
    FILE_READ_FAILED = "file_read_failed"
    FILE_NOT_FOUND = "file_not_found"
