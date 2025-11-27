from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class FileResponse(BaseModel):
    """Response model for file upload."""

    orig_name: str
    file_path: str


class MultipleFileResponse(BaseModel):
    """Response model for multiple file uploads."""

    files: List[FileResponse]
    count: int
