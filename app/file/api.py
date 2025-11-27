from fastapi import APIRouter, UploadFile, Depends, File, Form, Response
from typing import List
from sqlmodel import Session
from app.core.db_session import get_db
from app.file.service import FileService
from app.file.schema import FileResponse
from app.file.exception import FileException, FileError
from app.core.auth import get_current_user
from app.account.model import User

router = APIRouter(prefix="/file", tags=["file"])


@router.post("/upload", response_model=FileResponse)
async def upload_file(
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a single file to the server.
    The file will be stored with a UUID name and marked as temporary.
    """
    try:
        relative_path = await FileService.save_uploaded_file(file)
        return FileResponse(orig_name=file.filename, file_path=relative_path)
    except Exception as e:
        raise FileException(
            status_code=500,
            error_name=FileError.FILE_UPLOAD_FAILED,
            error_msg=f"Error uploading file: {str(e)}",
            input_params={"filename": file.filename},
        )


@router.post("/upload-multiple", response_model=List[FileResponse])
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload multiple files to the server.
    Each file will be stored with a UUID name and marked as temporary.
    """
    try:
        results = []
        for file in files:
            relative_path = await FileService.save_uploaded_file(file)
            results.append(
                FileResponse(orig_name=file.filename, file_path=relative_path)
            )
        return results
    except Exception as e:
        raise FileException(
            status_code=500,
            error_name=FileError.FILE_UPLOAD_FAILED,
            error_msg=f"Error uploading files: {str(e)}",
            input_params={"filenames": [file.filename for file in files]},
        )


@router.delete("/{file_path:path}")
async def delete_file(
    file_path: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a file from the server.
    """
    try:
        FileService.delete_file(file_path)
        return {
            "status": "success",
            "message": f"File {file_path} deleted successfully",
        }
    except Exception as e:
        raise FileException(
            status_code=500,
            error_name=FileError.FILE_DELETE_FAILED,
            error_msg=f"Error deleting file: {str(e)}",
            input_params={"file_path": file_path},
        )


@router.post("/cleanup")
async def cleanup_temp_files(
    session: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    Clean up temporary files older than 1 day.
    """
    try:
        count = FileService.cleanup_temp_files()
        return {"status": "success", "message": f"Cleaned up {count} temporary files"}
    except Exception as e:
        raise FileException(
            status_code=500,
            error_name=FileError.FILE_CLEANUP_FAILED,
            error_msg=f"Error cleaning up files: {str(e)}",
        )


@router.get("/{file_path:path}")
async def get_file_content(file_path: str, session: Session = Depends(get_db)):
    """
    Get the content of a file by its path.

    Args:
        file_path: The relative path to the file

    Returns:
        The file content as a stream
    """
    try:
        content = FileService.read_file_content(file_path)
        # Try to determine the file's MIME type based on its extension
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        # Default to application/octet-stream if the MIME type can't be determined
        if mime_type is None:
            mime_type = "application/octet-stream"

        return Response(content=content, media_type=mime_type)
    except FileNotFoundError as e:
        raise FileException(
            status_code=404,
            error_name=FileError.FILE_NOT_FOUND,
            error_msg=str(e),
            input_params={"file_path": file_path},
        )
    except Exception as e:
        raise FileException(
            status_code=500,
            error_name=FileError.FILE_READ_FAILED,
            error_msg=f"Error reading file: {str(e)}",
            input_params={"file_path": file_path},
        )
