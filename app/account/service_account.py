from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
import uuid

from sqlalchemy.orm import Session
from fastapi import status

from app.account.model import User, Role, RoleType
from app.core.auth import get_password_hash, verify_password
import app.account.service_auth as auth_service
from app.account.exception_account import AccountException, AccountError
from app.utils.utils import get_beijing_time


def get_user(
    db: Session, user_id: uuid.UUID, raise_exception: bool = False
) -> Optional[User]:
    """
    Get user by ID

    Args:
        db: Database session
        user_id: User UUID
        raise_exception: Whether to raise UserException when user not found (default: False)

    Returns:
        User object or None if not found and raise_exception is False

    Raises:
        UserException: If user not found and raise_exception is True
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user and raise_exception:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    return user


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Get user by username"""
    return db.query(User).filter(User.username == username).first()


def get_user_by_phone(db: Session, phone: str) -> Optional[User]:
    """Get user by phone number"""
    return db.query(User).filter(User.phone == phone).first()


def get_users(
    db: Session,
    page_num: int,
    page_size: int,
    username: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = True,
) -> Tuple[List[User], int]:
    """Get all users with optional filtering"""
    query = db.query(User)

    # Apply filters if provided
    if username:
        query = query.filter(User.username.ilike(f"%{username}%"))
    if phone:
        query = query.filter(User.phone.ilike(f"%{phone}%"))
    if name:
        query = query.filter(User.name.ilike(f"%{name}%"))
    if role:
        query = query.join(User.roles).filter(Role.name == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)  # Apply is_active filter

    # Get total count for pagination
    total = query.count()

    # Calculate skip based on page_num and page_size
    skip = (page_num - 1) * page_size

    # Apply pagination
    users = query.offset(skip).limit(page_size).all()

    return users, total


def create_user(
    db: Session, user_data: Dict[str, Any], role_names: Optional[List[str]] = None
) -> User:
    """Create a new user"""
    # Check if username is already taken
    if user_data.get("username"):
        existing_user = get_user_by_username(db, user_data["username"])
        if existing_user:
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.USERNAME_ALREADY_TAKEN,
                error_msg="Username already taken",
                input_params={"username": user_data.get("username")},
            )

    # Check if phone number is already registered
    if user_data.get("phone"):
        existing_user = get_user_by_phone(db, user_data["phone"])
        if existing_user:
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.PHONE_ALREADY_REGISTERED,
                error_msg="Phone number already registered",
                input_params={"phone": user_data.get("phone")},
            )

    # Hash the password if provided
    if password := user_data.get("password"):
        auth_service.validate_password_complexity(password)
        user_data["hashed_password"] = get_password_hash(password)

    # Remove plain password from data before storing
    user_data.pop("password", None)

    # Create user
    user = User(**user_data)

    # Add roles based on provided role names or default to CLIENT
    if role_names:
        roles = db.query(Role).filter(Role.name.in_(role_names)).all()
        if len(roles) != len(role_names):
            raise AccountException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AccountError.ROLES_NOT_FOUND,
                error_msg="One or more roles not found",
                input_params={"role_names": role_names},
            )
        user.roles = roles
    else:
        default_role = db.query(Role).filter(Role.name == RoleType.CLIENT).first()
        if not default_role:
            default_role = Role(name=RoleType.CLIENT, description="Regular user")
            db.add(default_role)
            db.commit()
            db.refresh(default_role)
        user.roles = [default_role]

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def update_user(db: Session, user_id: uuid.UUID, user_data: Dict[str, Any]) -> User:
    """Update user information"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Update fields
    for key, value in user_data.items():
        if hasattr(user, key) and value is not None:
            setattr(user, key, value)

    # Update timestamp with Beijing time
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def update_user_password(
    db: Session, user_id: uuid.UUID, old_password: str, new_password: str
) -> bool:
    """Update user password"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Verify old password
    if not verify_password(old_password, user.hashed_password):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.INCORRECT_PASSWORD,
            error_msg="Incorrect password",
            input_params={"user_id": str(user_id)},
        )

    # Update password
    auth_service.validate_password_complexity(new_password)
    user.hashed_password = get_password_hash(new_password)
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()

    return True


def update_user_phone(
    db: Session, user_id: uuid.UUID, new_phone: str, code: str
) -> bool:
    """Update user phone number (requires verification)"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Check if phone number is already taken by another user
    existing_user = get_user_by_phone(db, new_phone)
    if existing_user:
        raise AccountException(
            status_code=status.HTTP_409_CONFLICT,
            error_name=AccountError.PHONE_ALREADY_REGISTERED,
            error_msg="Phone number already registered",
            input_params={"phone": new_phone},
        )

    # Verify the code for the new phone number
    if not auth_service.verify_code(new_phone, code):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.INVALID_VERIFICATION_CODE,
            error_msg="Invalid verification code",
            input_params={"phone": new_phone, "code": code},
        )

    # Update phone number
    user.phone = new_phone
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()

    return True


def admin_reset_password(db: Session, user_id: uuid.UUID, new_password: str) -> bool:
    """Reset user password (admin function)"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Update password
    auth_service.validate_password_complexity(new_password)
    user.hashed_password = get_password_hash(new_password)
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()

    return True


def update_user_roles(db: Session, user_id: uuid.UUID, role_names: List[str]) -> User:
    """Update user roles using role names"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Get roles from names
    roles = db.query(Role).filter(Role.name.in_(role_names)).all()

    # Validate that all roles exist
    if len(roles) != len(role_names):
        raise AccountException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AccountError.ROLES_NOT_FOUND,
            error_msg="One or more roles not found",
            input_params={"role_names": role_names},
        )

    # Update user roles
    user.roles = roles
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def delete_user(db: Session, user_id: uuid.UUID) -> bool:
    """Delete a user"""
    user = get_user(db, user_id)

    if not user:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.USER_NOT_FOUND,
            error_msg="User not found",
            input_params={"user_id": str(user_id)},
        )

    # Instead of hard delete, set inactive (soft delete)
    user.is_active = False
    user.updated_at = get_beijing_time()

    db.add(user)
    db.commit()

    return True


def batch_delete_users(db: Session, user_ids: List[uuid.UUID]) -> Dict[str, Any]:
    """Batch delete multiple users"""
    results = {"success": [], "failed": []}

    for user_id in user_ids:
        try:
            user = get_user(db, user_id)
            if not user:
                results["failed"].append(
                    {"id": str(user_id), "reason": "User not found"}
                )
                continue

            # Instead of hard delete, set inactive (soft delete)
            user.is_active = False
            user.updated_at = get_beijing_time()

            db.add(user)
            results["success"].append(str(user_id))
        except Exception as e:
            results["failed"].append({"id": str(user_id), "reason": str(e)})

    db.commit()
    return results


# Role management functions


def get_role(db: Session, role_id: uuid.UUID) -> Optional[Role]:
    """Get role by ID"""
    return db.query(Role).filter(Role.id == role_id).first()


def get_role_by_name(db: Session, name: str) -> Optional[Role]:
    """Get role by name"""
    return db.query(Role).filter(Role.name == name).first()


def get_roles(db: Session, skip: int = 0, limit: int = 100) -> List[Role]:
    """Get all roles"""
    return db.query(Role).offset(skip).limit(limit).all()


def create_role(db: Session, name: str, description: Optional[str] = None) -> Role:
    """Create a new role"""
    role = Role(name=name, description=description)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def update_role(
    db: Session,
    role_id: uuid.UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Role:
    """Update role information"""
    role = get_role(db, role_id)

    if not role:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.ROLE_NOT_FOUND,
            error_msg="Role not found",
            input_params={"role_id": str(role_id)},
        )

    if name is not None:
        role.name = name

    if description is not None:
        role.description = description

    db.add(role)
    db.commit()
    db.refresh(role)

    return role


def delete_role(db: Session, role_id: uuid.UUID) -> bool:
    """Delete a role"""
    role = get_role(db, role_id)

    if not role:
        raise AccountException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AccountError.ROLE_NOT_FOUND,
            error_msg="Role not found",
            input_params={"role_id": str(role_id)},
        )

    db.delete(role)
    db.commit()

    return True
