import os
import uuid6
import xattr
from fastapi import UploadFile, HTTPException
from datetime import datetime, timedelta
from app.core.config import settings


class FileService:
    """Service for handling file operations."""

    @staticmethod
    async def save_uploaded_file(file: UploadFile) -> str:
        """
        Save an uploaded file with a UUID name but preserve extension.
        Mark it as temporary using xattr.
        """
        # Get file extension from the original filename
        _, ext = os.path.splitext(file.filename)

        # Generate a unique filename with UUID
        unique_filename = f"{uuid6.uuid7()}{ext}"

        # Create relative path for storage
        relative_path = os.path.join(datetime.now().strftime("%Y/%m"), unique_filename)

        # Create full path for storage
        full_path = os.path.join(settings.UPLOAD_BASE_PATH, relative_path)

        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Save the file
        with open(full_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        # Mark file as temporary using xattr
        try:
            xattr.setxattr(full_path, "user.temp", b"true")
        except Exception as e:
            print(f"Warning: Failed to set xattr: {e} - service.py:42")

        return relative_path

    @staticmethod
    def mark_file_as_permanent(file_path: str) -> None:
        """Mark a file as permanent by removing the temp xattr."""
        # Create full path for the file
        full_path = os.path.join(settings.UPLOAD_BASE_PATH, file_path)

        # Remove the temporary attribute
        try:
            xattr.removexattr(full_path, "user.temp")
        except Exception as e:
            print(f"Warning: Failed to remove xattr: {e} - service.py:56")

    @staticmethod
    def delete_file(file_path: str) -> None:
        """Delete a file from the filesystem."""
        # Create full path for the file
        full_path = os.path.join(settings.UPLOAD_BASE_PATH, file_path)

        # Delete the file if it exists
        if os.path.exists(full_path):
            os.remove(full_path)

    @staticmethod
    def cleanup_temp_files() -> int:
        """
        Delete temporary files older than 1 day.
        Returns the number of files deleted.
        """
        count = 0
        one_day_ago = datetime.now() - timedelta(days=1)

        # Walk through the base path
        for root, _, files in os.walk(settings.UPLOAD_BASE_PATH):
            for file in files:
                full_path = os.path.join(root, file)

                try:
                    # Check if file has the temp attribute
                    is_temp = False
                    try:
                        is_temp = xattr.getxattr(full_path, "user.temp") == b"true"
                    except:
                        continue

                    if is_temp:
                        # Check if file is older than 1 day
                        mod_time = datetime.fromtimestamp(os.path.getmtime(full_path))
                        if mod_time < one_day_ago:
                            os.remove(full_path)
                            count += 1
                except Exception as e:
                    print(f"Error during temp file cleanup: {e} - service.py:97")

        return count

    @staticmethod
    def read_file_content(file_path: str) -> bytes:
        """
        Read and return the content of a file.

        Args:
            file_path: Relative path to the file

        Returns:
            The bytes content of the file

        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        # Create full path for the file
        full_path = os.path.join(settings.UPLOAD_BASE_PATH, file_path)

        # Check if the file exists
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Read and return the file content
        with open(full_path, "rb") as file:
            return file.read()
