from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
from pydantic import ConfigDict
from enum import Enum
import uuid
from sqlalchemy import Column, Text, Index, text, TIMESTAMP, BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
import uuid6
from app.utils.utils import get_beijing_time

# 使用 TYPE_CHECKING 处理循环引用
if TYPE_CHECKING:
    from app.account.model import User


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"  # Not submitted for approval yet
    PENDING = "PENDING"  # Submitted, waiting for approval
    APPROVED = "APPROVED"  # Approved by staff
    REJECTED = "REJECTED"  # Rejected by staff


class Agent(SQLModel, table=True):
    __tablename__ = "agent"
    # 添加部分唯一约束，只在 is_active=true 时对 name+version 要求唯一
    __table_args__ = (
        Index(
            "uq_agent_name_version_active",  # 索引名称
            "name",
            "version",  # 索引字段
            unique=True,  # 设置为唯一索引
            postgresql_where=text("is_active = true"),  # 部分索引条件
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid6.uuid7,
        primary_key=True,
        index=True,
    )
    aic: Optional[str] = Field(
        default=None, sa_column=Column(String(), unique=True, index=True)
    )
    name: str = Field(index=True, max_length=255)
    version: str = Field(index=True, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text)  # 映射到 PostgreSQL 的 TEXT 类型
    )

    # Agent visual and integration fields
    logo_url: Optional[str] = Field(default=None, max_length=1000)
    # acp_url: Optional[str] = Field(default=None, max_length=1000)
    acs: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    acs_hash: Optional[str] = Field(default=None, max_length=256)  # acs 的checksum。
    acs_version: int = Field(default=1)  # acs版本号，每次acs变化时自增
    acs_last_seq: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, index=True)
    )  # 最后一次acs变化对应的seq号

    # Ontology/Entity 区分
    # True = 本体 (Ontology)，可以派生实体
    # False = 实体 (Entity) 或传统 Agent（本体与实体合一）
    is_ontology: bool = Field(default=False, index=True)

    # Status
    is_active: bool = Field(default=True)
    # 用户删除标志
    is_deleted: bool = Field(default=False)
    deleted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )
    deleted_reason: Optional[str] = Field(default=None, max_length=255)
    # 业务员禁用标志
    is_disabled: bool = Field(default=False)
    disabled_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )
    disabled_reason: Optional[str] = Field(default=None, max_length=255)

    # Registration information
    created_by_id: uuid.UUID = Field(foreign_key="account_user.id")
    # 使用带时区的时间戳类型
    created_at: datetime = Field(
        default_factory=get_beijing_time,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 指定使用带时区的时间戳
    )
    updated_at: datetime = Field(
        default_factory=get_beijing_time,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 指定使用带时区的时间戳
    )

    # Approval information
    submitted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 指定使用带时区的时间戳
    )
    approval_status: ApprovalStatus = Field(default=ApprovalStatus.DRAFT)
    processed_by_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="account_user.id"
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True)),  # 指定使用带时区的时间戳
    )
    process_comments: Optional[str] = Field(default=None, max_length=2000)

    # Vector database reference
    vector_id: Optional[str] = None

    # 定义 ORM 关系
    created_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "Agent.created_by_id",
            "primaryjoin": "Agent.created_by_id == User.id",
        }
    )
    processed_by: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "Agent.processed_by_id",
            "primaryjoin": "Agent.processed_by_id == User.id",
        }
    )

    model_config = ConfigDict(from_attributes=True)


# 这个导入放在文件末尾，避免循环导入问题
from app.account.model import User
