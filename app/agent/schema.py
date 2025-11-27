from pydantic import BaseModel, Field, validator, field_validator
from typing import Optional, List
from datetime import datetime
import uuid

from app.agent.model import ApprovalStatus
from app.account.schema_account import UserResponse
from app.utils.utils import utc_to_beijing, beijing_to_utc, BEIJING_TIMEZONE


class AgentBase(BaseModel):
    name: str = Field(..., max_length=255)
    version: str = Field(..., max_length=255)
    description: Optional[str] = None

    logo_url: Optional[str] = Field(None, max_length=1000)
    is_acp_support: bool = False
    acs: Optional[str] = None
    is_a2a_support: bool = False
    a2a_url: Optional[str] = Field(None, max_length=1000)
    is_anp_support: bool = False
    anp_url: Optional[str] = Field(None, max_length=1000)

    @field_validator("acs")
    @classmethod
    def validate_acs(cls, v, info):
        values = info.data
        if values.get("is_acp_support", False) and not v:
            raise ValueError("acs is required when is_acp_support is True")
        return v

    @field_validator("a2a_url")
    @classmethod
    def validate_a2a_url(cls, v, info):
        values = info.data
        if values.get("is_a2a_support", False) and not v:
            raise ValueError("a2a_url is required when is_a2a_support is True")
        return v

    @field_validator("anp_url")
    @classmethod
    def validate_anp_url(cls, v, info):
        values = info.data
        if values.get("is_anp_support", False) and not v:
            raise ValueError("anp_url is required when is_anp_support is True")
        return v


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    version: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None

    logo_url: Optional[str] = Field(None, max_length=1000)
    is_acp_support: Optional[bool] = None
    acs: Optional[str] = None
    is_a2a_support: Optional[bool] = None
    a2a_url: Optional[str] = Field(None, max_length=1000)
    is_anp_support: Optional[bool] = None
    anp_url: Optional[str] = Field(None, max_length=1000)

    @field_validator("acs")
    @classmethod
    def validate_acs_update(cls, v, info):
        values = info.data
        if values.get("is_acp_support") and not v:
            raise ValueError("acs is required when is_acp_support is True")
        return v

    @field_validator("a2a_url")
    @classmethod
    def validate_a2a_url_update(cls, v, info):
        values = info.data
        if values.get("is_a2a_support") and not v:
            raise ValueError("a2a_url is required when is_a2a_support is True")
        return v

    @field_validator("anp_url")
    @classmethod
    def validate_anp_url_update(cls, v, info):
        values = info.data
        if values.get("is_anp_support") and not v:
            raise ValueError("anp_url is required when is_anp_support is True")
        return v


class AgentProcessRequest(BaseModel):
    approve: bool
    comments: Optional[str] = Field(None, max_length=2000)


class AgentSearchQuery(BaseModel):
    query: str
    page_num: int = 1
    page_size: int = 10


class AgentResponse(AgentBase):
    id: uuid.UUID
    aic: Optional[str] = Field(None, max_length=32)
    acs_hash: Optional[str] = Field(None, max_length=256)
    acs_version: int = 1
    acs_last_seq: Optional[int] = None
    is_active: bool
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    deleted_reason: Optional[str] = Field(None, max_length=255)
    is_disabled: bool = False
    disabled_at: Optional[datetime] = None
    disabled_reason: Optional[str] = Field(None, max_length=255)
    approval_status: ApprovalStatus
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime] = None
    processed_by_id: Optional[uuid.UUID] = None
    processed_at: Optional[datetime] = None
    process_comments: Optional[str] = Field(None, max_length=2000)
    vector_id: Optional[str] = None

    # 添加datetime字段的验证器，确保返回时带有北京时区信息并采用ISO 8601格式
    @field_validator(
        "created_at",
        "updated_at",
        "submitted_at",
        "processed_at",
        "deleted_at",
        "disabled_at",
        mode="before",
    )
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

    # 添加模型配置确保JSON序列化时使用ISO格式
    class Config:
        from_attributes = True  # 替换 orm_mode = True，适配 Pydantic V2
        json_encoders = {
            # 确保datetime在JSON序列化时使用ISO格式带时区
            datetime: lambda dt: (
                dt.isoformat()
                if dt.tzinfo
                else dt.replace(tzinfo=BEIJING_TIMEZONE).isoformat()
            )
        }


class AgentDetailResponse(AgentResponse):
    """包含完整用户信息的 Agent 响应模型，仅用于详情接口"""

    created_by: Optional[UserResponse] = None
    processed_by: Optional[UserResponse] = None


class AgentListResponse(BaseModel):
    items: List[AgentDetailResponse]
    total: int
    page_num: int = 1
    page_size: int = 10

    class Config:
        json_encoders = {
            # 确保datetime在JSON序列化时使用ISO格式带时区
            datetime: lambda dt: (
                dt.isoformat()
                if dt.tzinfo
                else dt.replace(tzinfo=BEIJING_TIMEZONE).isoformat()
            )
        }


class AgentSearchResponse(BaseModel):
    items: List[AgentDetailResponse]
    total: int
    page_num: int
    page_size: int

    class Config:
        json_encoders = {
            # 确保datetime在JSON序列化时使用ISO格式带时区
            datetime: lambda dt: (
                dt.isoformat()
                if dt.tzinfo
                else dt.replace(tzinfo=BEIJING_TIMEZONE).isoformat()
            )
        }
