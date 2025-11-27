from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any

from fastapi import Depends, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db_session import get_db
from app.account.model import User, RoleType
from app.account.exception_auth import AuthException, AuthError
from app.utils.utils import get_beijing_time

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash from plain text password"""
    return pwd_context.hash(password)


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Create a new JWT token"""
    to_encode = data.copy()
    # 使用北京时间作为基准计算过期时间
    expire = get_beijing_time() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Get current user from JWT token and validate against stored token"""
    credentials_exception = AuthException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        error_name=AuthError.TOKEN_VALIDATION_ERROR,
        error_msg="Could not validate credentials",
        input_params={"token": "***"},
    )
    try:
        # Check if token has been revoked
        from app.account.service_auth import is_token_revoked

        if is_token_revoked(token):
            raise credentials_exception

        # Decode the token
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Get the user
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AuthException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_name=AuthError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": user_id},
        )

    # Check if user is active
    if not user.is_active:
        raise AuthException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AuthError.INACTIVE_USER,
            error_msg="Inactive user",
            input_params={"user_id": user_id},
        )

    # Verify stored token matches current token
    if not user.access_token or user.access_token != token:
        raise credentials_exception

    # Check if token has expired based on stored expiration time
    if user.token_expires_at and get_beijing_time() > user.token_expires_at:
        raise AuthException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_name=AuthError.EXPIRED_TOKEN,
            error_msg="Token has expired",
            input_params={"token": "***"},
        )

    return user


def get_optional_token(request: Request) -> Optional[str]:
    """
    获取 Authorization header，如果没有则返回 None。
    """
    auth: str = request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def safe_get_current_user(
    token: Optional[str] = Depends(get_optional_token), db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Like get_current_user, but returns None if not logged in or token invalid/expired.
    """
    from app.account.service_auth import is_token_revoked

    if not token:
        return None
    try:
        if is_token_revoked(token):
            return None
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except Exception:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None
    if not user.access_token or user.access_token != token:
        return None
    if user.token_expires_at and get_beijing_time() > user.token_expires_at:
        return None
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Check if current user is active"""
    if not current_user.is_active:
        raise AuthException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AuthError.INACTIVE_USER,
            error_msg="Inactive user",
            input_params={"user_id": str(current_user.id)},
        )
    return current_user


def check_user_role(required_roles: list[Union[str, RoleType]]):
    """Check if user has required roles"""

    async def _check_user_role(current_user: User = Depends(get_current_user)):
        # Check if any of the user's roles matches required roles
        user_roles = [role.name for role in current_user.roles]
        if not any(role in required_roles for role in user_roles):
            raise AuthException(
                status_code=status.HTTP_403_FORBIDDEN,
                error_name=AuthError.INSUFFICIENT_PERMISSIONS,
                error_msg=f"User does not have required roles: {required_roles}",
                input_params={
                    "user_id": str(current_user.id),
                    "user_roles": user_roles,
                    "required_roles": required_roles,
                },
            )
        return current_user

    return _check_user_role
