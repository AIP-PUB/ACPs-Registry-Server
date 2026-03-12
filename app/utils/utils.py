from typing import Optional
from datetime import datetime, timezone, timedelta
import hashlib


def parse_boolean_string(bool_str: Optional[str]) -> Optional[bool]:
    """
    Convert a string representation to a boolean value or None.

    Args:
        bool_str: String representation of a boolean value

    Returns:
        - True for strings like 'true', '1', 'yes' (case insensitive)
        - False for strings like 'false', '0', 'no' (case insensitive)
        - None for empty strings or None input
    """
    if bool_str is None or bool_str == "":
        return None

    normalized = bool_str.lower()

    if normalized in ("true", "1", "yes", "t"):
        return True
    elif normalized in ("false", "0", "no", "f"):
        return False

    return None


# Beijing timezone (UTC+8)
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def get_beijing_time() -> datetime:
    """
    Get current time in Beijing timezone (UTC+8).

    Returns:
        Current datetime in Beijing timezone with tzinfo
    """
    return datetime.now(BEIJING_TIMEZONE)


def utc_to_beijing(dt: datetime) -> datetime:
    """
    Convert UTC datetime to Beijing timezone (UTC+8).

    Args:
        dt: The datetime object to convert (with or without tzinfo)

    Returns:
        Datetime in Beijing timezone with tzinfo
    """
    # If the datetime has no timezone info, assume it's UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Convert to Beijing time
    return dt.astimezone(BEIJING_TIMEZONE)


def beijing_to_utc(dt: datetime) -> datetime:
    """
    Convert Beijing timezone datetime to UTC.

    Args:
        dt: The datetime object to convert (with or without tzinfo)

    Returns:
        Datetime in UTC timezone with tzinfo
    """
    # If the datetime has no timezone info, assume it's Beijing time
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING_TIMEZONE)

    # Convert to UTC
    return dt.astimezone(timezone.utc)


def sha256(text: str) -> str:
    """
    Calculate SHA256 hash of input text and return as hexadecimal string.

    Args:
        text: Input text to calculate hash for

    Returns:
        SHA256 hash as hexadecimal string
    """
    if not text:
        return ""

    # Encode the text to bytes and calculate SHA256 hash
    hash_object = hashlib.sha256(text.encode("utf-8"))
    # Return the hexadecimal representation
    return hash_object.hexdigest()
