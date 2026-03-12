from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    Text,
    Sequence,
    BigInteger,
    TIMESTAMP,
    text,
    String,
    Integer,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
import uuid
from app.utils.utils import get_beijing_time


# PostgreSQL全局序列生成器，使用BIGINT避免溢出
global_seq = Sequence("global_seq", start=1, increment=1)


class ChangeLog(SQLModel, table=True):
    """数据变更日志表，记录所有数据变更的信息"""

    __tablename__ = "change_log"

    # 全局序列号作为主键，使用BIGINT避免溢出
    seq: int = Field(
        sa_column=Column(
            BigInteger,
            primary_key=True,
            server_default=text("nextval('global_seq')"),
            index=True,
        )
    )

    # 时间戳
    ts: datetime = Field(
        default_factory=get_beijing_time, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 数据类型，目前只有 acs (Agent Capability Specification)
    type: str = Field(default="acs", max_length=50, index=True)

    # 操作类型：upsert 或 delete，默认为 upsert
    op: str = Field(default="upsert", max_length=10, index=True)

    # 对象ID，对应Agent.aic
    id: str = Field(max_length=255, index=True)

    # 对象版本号，对应Agent.acs_version
    version: int = Field(index=True)

    # 数据载荷，对应Agent.acs字段的内容
    payload: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))

    model_config = ConfigDict(from_attributes=True)


class Snapshot(SQLModel, table=True):
    """快照表，用于存储快照的元数据信息"""

    __tablename__ = "snapshot"

    # 快照的唯一标识符，使用UUID字符串形式
    id: str = Field(primary_key=True, max_length=50, index=True)

    # 快照的数据类型，逗号分隔的字符串
    types: str = Field(max_length=255, index=True)

    # 快照的切点序列号
    seq: int = Field(sa_column=Column(BigInteger, index=True))

    # 快照的总chunk数量
    chunk_total: int = Field(default=1)

    # 快照包含的总对象数量
    object_count: int = Field(default=0)

    # 增量快照的起始序列号，None表示全量快照
    from_seq: Optional[int] = Field(default=None, sa_column=Column(BigInteger))

    # 快照是否被删除
    is_deleted: bool = Field(default=False, index=True)

    # 创建时间
    created_at: datetime = Field(
        default_factory=get_beijing_time, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 最后访问时间
    last_access_at: datetime = Field(
        default_factory=get_beijing_time, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 过期时间
    expire_at: datetime = Field(sa_column=Column(TIMESTAMP(timezone=True)))

    model_config = ConfigDict(from_attributes=True)


class WebHook(SQLModel, table=True):
    """WebHook表，用于存储WebHook配置和状态信息"""

    __tablename__ = "webhook"

    # WebHook的唯一标识符，使用UUID字符串形式
    id: str = Field(primary_key=True, max_length=50, index=True)

    # 回调URL
    url: str = Field(max_length=2000, index=True)

    # 签名密钥，用于HMAC-SHA256签名验证
    secret: str = Field(max_length=500)

    # 关注的数据类型，逗号分隔的字符串，如"acs,dataset"
    types: str = Field(max_length=255, index=True)

    # 关注的事件类型，逗号分隔的字符串，如"data_change,retention_cleanup"
    events: str = Field(max_length=255, index=True)

    # WebHook描述信息
    description: Optional[str] = Field(default=None, max_length=500)

    # WebHook状态：active, failed, disabled
    status: str = Field(default="active", max_length=20, index=True)

    # 失败计数
    failure_count: int = Field(default=0)

    # 下次重试时间
    next_retry_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 最后触发时间
    last_triggered_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 最后成功时间
    last_success_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 最后失败时间
    last_failure_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 最后失败原因
    last_failure_reason: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 创建时间
    created_at: datetime = Field(
        default_factory=get_beijing_time, sa_column=Column(TIMESTAMP(timezone=True))
    )

    # 更新时间
    updated_at: datetime = Field(
        default_factory=get_beijing_time, sa_column=Column(TIMESTAMP(timezone=True))
    )

    model_config = ConfigDict(from_attributes=True)
