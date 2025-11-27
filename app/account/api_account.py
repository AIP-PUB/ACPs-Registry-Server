from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.orm import Session

from app.core.db_session import get_db
from app.core.auth import get_current_user, check_user_role
from app.account.model import User, RoleType
from app.account.schema_account import (
    UserResponse,
    UserListResponse,
    UserCreate,
    UserUpdate,
    PasswordUpdate,
    PhoneUpdate,
    AdminPasswordReset,
    UserRoleUpdate,
    RoleResponse,
    RoleCreate,
    RoleUpdate,
)
from app.account.service_account import (
    get_user,
    get_users,
    create_user,
    update_user,
    update_user_password,
    update_user_phone,
    admin_reset_password,
    update_user_roles,
    delete_user,
    batch_delete_users,
    get_roles,
    create_role,
    update_role,
    delete_role,
)
from app.utils.utils import parse_boolean_string

router = APIRouter(prefix="/account", tags=["account"])


# Current user endpoints
@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get information about the currently authenticated user
    """
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update information for the currently authenticated user
    """
    updated_user = update_user(
        db, current_user.id, user_update.dict(exclude_unset=True)
    )
    return updated_user


@router.put("/me/password", response_model=dict)
async def update_current_user_password(
    password_update: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update password for the currently authenticated user
    """
    success = update_user_password(
        db, current_user.id, password_update.old_password, password_update.new_password
    )
    return {"success": success, "message": "Password updated successfully"}


@router.put("/me/phone", response_model=dict)
async def update_current_user_phone(
    phone_update: PhoneUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update phone number for the currently authenticated user (requires verification)
    """
    success = update_user_phone(
        db, current_user.id, phone_update.new_phone, phone_update.verify_code
    )
    return {"success": success, "message": "Phone number updated successfully"}


# Admin user management endpoints
@router.get("/user", response_model=UserListResponse)
async def read_users(
    page_num: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1),
    username: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Get all users with optional filtering (admin only)
    """
    # Convert is_active string to boolean or None using utility function
    is_active_bool = parse_boolean_string(is_active)

    users, total = get_users(
        db, page_num, page_size, username, phone, name, role, is_active_bool
    )
    return {
        "items": users,
        "total": total,
        "page_num": page_num,
        "page_size": page_size,
    }


@router.post("/user", response_model=UserResponse)
async def create_new_user(
    user_create: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Create a new user (admin only)
    """
    user = create_user(
        db, user_create.dict(), user_create.roles
    )  # Pass roles to create_user
    return user


@router.get("/user/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN, RoleType.STAFF])),
):
    """
    Get a specific user by ID (admin/staff only)
    """
    return get_user(db, user_id, raise_exception=True)


@router.put("/user/{user_id}", response_model=UserResponse)
async def update_user_info(
    user_id: uuid.UUID,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Update a user (admin only)
    """
    updated_user = update_user(db, user_id, user_update.model_dump(exclude_unset=True))
    return updated_user


@router.put("/user/{user_id}/password", response_model=dict)
async def reset_user_password(
    user_id: uuid.UUID,
    password_reset: AdminPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Reset a user's password (admin only)
    """
    success = admin_reset_password(db, user_id, password_reset.new_password)
    return {"message": "Password reset successfully"}


@router.put("/user/{user_id}/roles", response_model=UserResponse)
async def update_user_role_assignments(
    user_id: uuid.UUID,
    role_update: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Update a user's roles using role names (admin only)
    """
    updated_user = update_user_roles(
        db, user_id, role_update.role_names
    )  # Pass role names instead of IDs
    return updated_user


@router.delete("/user/{user_id}", response_model=dict)
async def delete_user_account(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Delete a user (admin only)
    """
    success = delete_user(db, user_id)
    return {"success": success, "message": "User deleted successfully"}


@router.delete("/user", response_model=dict)
async def batch_delete_user_accounts(
    user_ids: List[uuid.UUID] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Batch delete multiple users (admin only)
    """
    results = batch_delete_users(db, user_ids)
    return results


# Role management endpoints
@router.get("/role", response_model=List[RoleResponse])
async def read_roles(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Get all roles (admin only)
    """
    roles = get_roles(db, skip, limit)
    return roles


@router.post("/role", response_model=RoleResponse)
async def create_new_role(
    role_create: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Create a new role (admin only)
    """
    role = create_role(db, role_create.name, role_create.description)
    return role


@router.put("/role/{role_id}", response_model=RoleResponse)
async def update_role_info(
    role_id: uuid.UUID,
    role_update: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Update a role (admin only)
    """
    updated_role = update_role(db, role_id, role_update.name, role_update.description)
    return updated_role


@router.delete("/role/{role_id}", response_model=dict)
async def delete_role_item(
    role_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.ADMIN])),
):
    """
    Delete a role (admin only)
    """
    success = delete_role(db, role_id)
    return {"message": "Role deleted successfully"}
