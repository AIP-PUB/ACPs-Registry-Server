from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import random
import string
import uuid
import re

from sqlalchemy.orm import Session
from fastapi import status

from app.core.config import settings
from app.core.auth import get_password_hash, verify_password, create_access_token
from app.account.model import User, Role, RoleType
from app.account.service_account import (
    get_user_by_phone,
    get_user_by_username,
    get_user,
)
from app.account.exception_account import AccountException, AccountError
from app.utils.utils import get_beijing_time

# Mock Redis client - in production, use a real Redis connection
mock_redis = {}

# Store for revoked tokens - in production, use Redis
revoked_tokens = set()


def generate_verification_code() -> str:
    """Generate a random 6-digit verification code"""
    return "".join(random.choices(string.digits, k=6))


def store_verification_code(phone: str, code: str, expires_in: int = 300) -> None:
    """Store verification code in Redis with expiration time"""
    # In a real implementation, this would use Redis
    mock_redis[phone] = {
        "code": code,
        "expires_at": get_beijing_time() + timedelta(seconds=expires_in),
    }


def verify_code(phone: str, code: str) -> bool:
    """Verify that the provided code matches the stored code for the phone number"""

    if code == "123456":
        # For demo purposes, we accept a hardcoded code
        return True
    # In a real implementation, this would use Redis
    if phone not in mock_redis:
        return False

    code_data = mock_redis[phone]
    if get_beijing_time() > code_data["expires_at"]:
        # Code expired
        del mock_redis[phone]
        return False

    # Check if code matches
    if code_data["code"] == code:
        # Delete the code once used
        del mock_redis[phone]
        return True

    return False


def send_verification_code(phone: str) -> str:
    """
    Send verification code via SMS
    In a real implementation, this would use an SMS service
    For demo purposes, we just return the code
    """
    code = generate_verification_code()
    store_verification_code(phone, code)
    # In a real implementation, this would send an SMS
    return code


def validate_password_complexity(password: str) -> None:
    """
    Validate password complexity:
    1. Length 8-20 characters
    2. Must contain uppercase letters
    3. Must contain lowercase letters
    4. Must contain numbers
    5. Must contain special characters (anything other than letters, numbers, or spaces)
    """
    if not (8 <= len(password) <= 20):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.PASSWORD_COMPLEXITY_ERROR,
            error_msg="Password must be between 8 and 20 characters",
        )

    if not re.search(r"[A-Z]", password):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.PASSWORD_COMPLEXITY_ERROR,
            error_msg="Password must contain at least one uppercase letter",
        )

    if not re.search(r"[a-z]", password):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.PASSWORD_COMPLEXITY_ERROR,
            error_msg="Password must contain at least one lowercase letter",
        )

    if not re.search(r"\d", password):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.PASSWORD_COMPLEXITY_ERROR,
            error_msg="Password must contain at least one number",
        )

    if not re.search(r"[^A-Za-z0-9\s]", password):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.PASSWORD_COMPLEXITY_ERROR,
            error_msg="Password must contain at least one special character",
        )
        

def register_user(db: Session, user_data: Dict[str, Any], code: str) -> User:
    """Register a new user after verification"""
    phone = user_data.get("phone")

    # For username/password registration (without phone verification)
    if not phone or not code:
        # Check if username is provided and not already taken
        username = user_data.get("username")
        if not username:
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.INVALID_REQUEST,
                error_msg="Username is required for registration without phone verification",
                input_params={"username": username},
            )

        existing_username = get_user_by_username(db, username)
        if existing_username:
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.USERNAME_ALREADY_TAKEN,
                error_msg="Username already taken",
                input_params={"username": username},
            )
    else:
        # For phone verification registration
        # Check if phone number is already registered
        existing_user = get_user_by_phone(db, phone)
        if existing_user:
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.PHONE_ALREADY_REGISTERED,
                error_msg="Phone number already registered",
                input_params={"phone": phone},
            )

        # Verify the code only if phone is provided
        if not verify_code(phone, code):
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.INVALID_VERIFICATION_CODE,
                error_msg="Invalid verification code",
                input_params={"phone": phone, "code": code},
            )

        # If using phone verification but username is also provided, check it
        if username := user_data.get("username"):
            existing_username = get_user_by_username(db, username)
            if existing_username:
                raise AccountException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AccountError.USERNAME_ALREADY_TAKEN,
                    error_msg="Username already taken",
                    input_params={"username": username},
                )

    # Hash the password if provided
    if password := user_data.get("password"):
        user_data["hashed_password"] = get_password_hash(password)

    # Remove plain password from data before storing
    user_data.pop("password", None)

    # Create new user
    user = User(**user_data)

    # Add default client role
    default_role = db.query(Role).filter(Role.name == RoleType.CLIENT).first()
    if not default_role:
        # Create default role if it doesn't exist
        default_role = Role(name=RoleType.CLIENT, description="Regular client")
        db.add(default_role)
        db.commit()
        db.refresh(default_role)

    user.roles = [default_role]

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def authenticate_user(
    db: Session, username: str, password: str, raise_exception: bool = False
) -> Optional[User]:
    """
    Authenticate a user with username/password

    Args:
        db: Database session
        username: Username to authenticate
        password: Password to verify
        raise_exception: Whether to raise UserException when authentication fails (default: False)

    Returns:
        Authenticated User object or None if authentication fails and raise_exception is False

    Raises:
        UserException: If authentication fails and raise_exception is True
    """
    user = get_user_by_username(db, username)

    if not user or not user.is_active:
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_CREDENTIALS,
                error_msg="Incorrect username or password",
                input_params={"username": username},
            )
        return None

    if not user.hashed_password:
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_CREDENTIALS,
                error_msg="Incorrect username or password",
                input_params={"username": username},
            )
        return None

    if not verify_password(password, user.hashed_password):
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_CREDENTIALS,
                error_msg="Incorrect username or password",
                input_params={"username": username},
            )
        return None

    return user


def authenticate_by_phone(
    db: Session, phone: str, code: str, raise_exception: bool = False
) -> Optional[User]:
    """
    Authenticate a user with phone/verification code

    Args:
        db: Database session
        phone: Phone number to authenticate
        code: Verification code to verify
        raise_exception: Whether to raise UserException when authentication fails (default: False)

    Returns:
        Authenticated User object or None if authentication fails and raise_exception is False

    Raises:
        UserException: If authentication fails and raise_exception is True
    """
    user = get_user_by_phone(db, phone)

    if not user or not user.is_active:
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_CREDENTIALS,
                error_msg="Invalid phone number or verification code",
                input_params={"phone": phone},
            )
        return None

    if not verify_code(phone, code):
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_VERIFICATION_CODE,
                error_msg="Invalid verification code",
                input_params={"phone": phone, "code": code},
            )
        return None

    return user


def create_user_token(user: User, db: Session = None) -> Dict[str, str]:
    """Create access token for authenticated user and update user's token info"""
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # 使用北京时间计算过期时间
    expires_at = get_beijing_time() + expires_delta

    # Use user ID as subject
    token_data = {"sub": str(user.id)}

    # Include roles in the token
    user_roles = [role.name for role in user.roles]
    token_data["roles"] = user_roles

    access_token = create_access_token(data=token_data, expires_delta=expires_delta)

    # Create refresh token (in a real app, this would have longer expiry and different structure)
    refresh_token = access_token  # For simplicity, we'll use the same token

    # Update user model with token information
    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = expires_at
    user.updated_at = get_beijing_time()

    # Save the user changes to the database if db session provided
    if db:
        db.add(user)
        db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),  # Include expiration time in ISO format with timezone
    }


def reset_password(db: Session, phone: str, code: str, new_password: str) -> bool:
    """Reset user password after verification"""
    user = get_user_by_phone(db, phone)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"phone": phone},
        )

    if not verify_code(phone, code):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.INVALID_VERIFICATION_CODE,
            error_msg="Invalid verification code",
            input_params={"phone": phone, "code": code},
        )

    user.hashed_password = get_password_hash(new_password)
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()

    return True


def invalidate_token(token: str) -> bool:
    """
    Invalidate a token (mark it as revoked)
    In a real implementation, this would store the token in Redis with expiration
    """
    revoked_tokens.add(token)
    return True


def is_token_revoked(token: str) -> bool:
    """
    Check if a token has been revoked
    In a real implementation, this would check if the token is in Redis
    """
    return token in revoked_tokens


def refresh_access_token(
    db: Session, refresh_token: str, raise_exception: bool = False
) -> Optional[Dict[str, str]]:
    """
    Refresh an access token using a refresh token

    Args:
        db: Database session
        refresh_token: Refresh token to use
        raise_exception: Whether to raise UserException when refresh fails (default: False)

    Returns:
        New token dictionary or None if refresh fails and raise_exception is False

    Raises:
        UserException: If refresh fails and raise_exception is True
    """
    try:
        # Verify the refresh token
        from app.core.auth import jwt, settings

        payload = jwt.decode(
            refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        user_id = payload.get("sub")
        if not user_id:
            if raise_exception:
                raise AccountException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    error_name=AccountError.INVALID_REFRESH_TOKEN,
                    error_msg="Invalid refresh token",
                    input_params={"refresh_token": "***"},
                )
            return None

        # Get the user
        user = get_user(db, uuid.UUID(user_id))
        if not user or not user.is_active:
            if raise_exception:
                raise AccountException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    error_name=AccountError.USER_NOT_FOUND,
                    error_msg="User not found or inactive",
                    input_params={"user_id": user_id},
                )
            return None

        # Verify that the provided refresh token matches the stored one
        if not user.refresh_token or user.refresh_token != refresh_token:
            if raise_exception:
                raise AccountException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    error_name=AccountError.INVALID_REFRESH_TOKEN,
                    error_msg="Invalid refresh token",
                    input_params={"refresh_token": "***"},
                )
            return None

        # Check if token is expired
        if user.token_expires_at and get_beijing_time() > user.token_expires_at:
            if raise_exception:
                raise AccountException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    error_name=AccountError.EXPIRED_TOKEN,
                    error_msg="Refresh token expired",
                    input_params={"refresh_token": "***"},
                )
            return None

        # Generate a new token
        return create_user_token(user, db)

    except Exception as e:
        if raise_exception:
            raise AccountException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_name=AccountError.INVALID_REFRESH_TOKEN,
                error_msg=f"Invalid refresh token: {str(e)}",
                input_params={"refresh_token": "***"},
            )
        return None
