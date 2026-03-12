from pydantic import (
    BaseModel,
    Field,
    EmailStr,
    field_validator,
    model_validator,
    ConfigDict,
)
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
from app.utils.utils import utc_to_beijing, BEIJING_TIMEZONE


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(RoleBase):
    name: Optional[str] = None


class RoleResponse(RoleBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    name: Optional[str] = None
    avatar: Optional[str] = None
    org_name: Optional[str] = None
    org_code: Optional[str] = None
    org_address: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def check_username_or_phone(cls, data):
        # Handle both dictionary-style access and object attribute access
        if isinstance(data, dict):
            username = data.get("username")
            phone = data.get("phone")
        else:
            # For ORM objects
            username = getattr(data, "username", None)
            phone = getattr(data, "phone", None)

        if username is None and phone is None:
            raise ValueError("Either username or phone must be provided")
        return data


class UserCreate(UserBase):
    password: Optional[str] = None
    roles: List[str]


class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    org_name: Optional[str] = None
    org_code: Optional[str] = None
    org_address: Optional[str] = None


class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str


class PhoneUpdate(BaseModel):
    new_phone: str
    verify_code: str


class UserRoleUpdate(BaseModel):
    role_names: List[str]


class UserStatusUpdate(BaseModel):
    is_active: bool


class AdminPasswordReset(BaseModel):
    new_password: str


class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    roles: List[str]  # List of role names as strings
    created_at: datetime
    updated_at: datetime
    token_expires_at: Optional[datetime] = None

    # 添加datetime字段的验证器，确保返回时带有北京时区信息并采用ISO 8601格式
    @field_validator("created_at", "updated_at", "token_expires_at", mode="before")
    @classmethod
    def convert_datetime_to_beijing(cls, v):
        if v is not None:
            # 将UTC时间转换为北京时间，并确保带有时区信息
            beijing_time = utc_to_beijing(v)
            # 确保时间以ISO 8601格式返回带时区信息
            if beijing_time.tzinfo is not None:
                return beijing_time
            # 如果没有时区信息，添加北京时区信息
            return beijing_time.replace(tzinfo=BEIJING_TIMEZONE)
        return v

    model_config = ConfigDict(from_attributes=True)

    @field_validator("roles", mode="before")
    @classmethod
    def extract_role_names(cls, v):
        if v and isinstance(v, list):
            return [role.name for role in v]
        return v


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page_num: Optional[int] = None
    page_size: Optional[int] = None
