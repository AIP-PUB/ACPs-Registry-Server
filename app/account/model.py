from datetime import datetime
from typing import List, Optional, TYPE_CHECKING, ForwardRef
from sqlmodel import Column, Field, SQLModel, Relationship
from pydantic import EmailStr, field_validator, ConfigDict
import uuid
import uuid6
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import TIMESTAMP
from enum import Enum
from app.utils.utils import get_beijing_time

# 条件导入以避免循环引用
if TYPE_CHECKING:
    from app.agent.model import Agent


class RoleType(str, Enum):
    CLIENT = "CLIENT"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class Role(SQLModel, table=True):
    __tablename__ = "account_role"

    id: uuid.UUID = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        #  sa_column=Field(sa_column=UUID(as_uuid=True)),
    )
    name: RoleType = Field(index=True)
    description: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Association table for user roles many-to-many relationship
class UserRoleLink(SQLModel, table=True):
    __tablename__ = "account_user_role_link"

    user_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="account_user.id", primary_key=True
    )
    role_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="account_role.id", primary_key=True
    )


class User(SQLModel, table=True):
    __tablename__ = "account_user"

    id: uuid.UUID = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
        # sa_column=Field(sa_column=UUID(as_uuid=True)),
    )
    username: Optional[str] = Field(default=None, index=True, unique=True)
    email: Optional[str] = Field(default=None, index=True, unique=True)
    phone: Optional[str] = Field(default=None, index=True, unique=True)
    hashed_password: Optional[str] = None

    # Profile information
    name: Optional[str] = None
    avatar: Optional[str] = None

    # Organization information
    org_name: Optional[str] = None
    org_code: Optional[str] = None
    org_address: Optional[str] = None

    # Token information
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))  # 使用带时区的时间戳
    )

    # Status
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=get_beijing_time,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 使用带时区的时间戳
    )
    updated_at: datetime = Field(
        default_factory=get_beijing_time,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 使用带时区的时间戳
    )

    # 基本关系
    roles: List[Role] = Relationship(link_model=UserRoleLink)

    # Agent 关系 - 创建的 Agents
    created_agents: List["Agent"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "Agent.created_by_id",
            "back_populates": "created_by",
        }
    )

    # Agent 关系 - 处理的 Agents
    processed_agents: List["Agent"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "Agent.processed_by_id",
            "back_populates": "processed_by",
        }
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("username", "phone")
    @classmethod
    def validate_identification(cls, v, info):
        # This validator will be called for both username and phone
        # For phone, we need to check if username was provided
        values = info.data
        if (
            v is None
            and "username" in values
            and values["username"] is None
            and "phone" in values
            and values["phone"] is None
        ):
            raise ValueError("Either username or phone must be provided")
        return v


# 解析循环引用 - 只需要导入 Agent 以完成关系解析
from app.agent.model import Agent
