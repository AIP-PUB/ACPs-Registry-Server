from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import uuid
import json

from app.agent.model import ApprovalStatus
from app.account.schema_account import UserResponse
from app.utils.utils import utc_to_beijing, beijing_to_utc, BEIJING_TIMEZONE
from app.utils import aic


class AgentBase(BaseModel):
    name: str = Field(..., max_length=255)
    version: str = Field(..., max_length=255)
    description: Optional[str] = None

    logo_url: Optional[str] = Field(None, max_length=1000)
    acs: Optional[Union[str, Dict[str, Any]]] = None
    # 是否为本体 (Ontology)
    # True = 本体，可通过 ATR 实体注册 API 派生实体
    # False = 传统 Agent（本体与实体合一）或实体
    is_ontology: bool = False

    # 协议支持字段（is_acp_support/is_a2a_support/is_anp_support）已从表结构移除。


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    version: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None

    logo_url: Optional[str] = Field(None, max_length=1000)
    acs: Optional[Union[str, Dict[str, Any]]] = None
    # 注意：is_ontology 一旦设置后不应该被修改，因此不在 Update 中提供
    # 如果需要更改，应该删除并重新创建

    # 协议支持字段移除后，不再基于 is_*_support 进行条件校验


class AgentProcessRequest(BaseModel):
    approve: bool
    comments: Optional[str] = Field(None, max_length=2000)


class AgentSearchQuery(BaseModel):
    query: str
    page_num: int = 1
    page_size: int = 10


class AgentResponse(AgentBase):
    id: uuid.UUID
    aic: Optional[str] = Field(None)
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

    @field_validator("acs", mode="before")
    @classmethod
    def normalize_acs(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v

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

    model_config = ConfigDict(from_attributes=True)


class AgentDetailResponse(AgentResponse):
    """包含完整用户信息的 Agent 响应模型，仅用于详情接口"""

    created_by: Optional[UserResponse] = None
    processed_by: Optional[UserResponse] = None


class AgentListResponse(BaseModel):
    items: List[AgentDetailResponse]
    total: int
    page_num: int = 1
    page_size: int = 10


class AgentSearchResponse(BaseModel):
    items: List[AgentDetailResponse]
    total: int
    page_num: int
    page_size: int


# -------------------------------------------------------------------
# ATR Entity Registration Schemas (按照 ATR-Registry-Server.md 规范定义)
# -------------------------------------------------------------------


class EndPoint(BaseModel):
    """
    服务端点定义
    """

    url: str = Field(..., description="服务端点 URL")
    security: List[dict] = Field(
        default_factory=list,
        description="安全方案配置，例如 [{'mtls': []}]",
    )
    transport: str = Field(
        default="JSONRPC",
        description="传输协议，可选值：JSONRPC, REST, GRPC",
    )


class EntityRegistrationRequest(BaseModel):
    """
    实体注册请求模型（ATR-Registry-Server.md 规范）

    用于基于已审批的本体 AIC，自动注册新的实体并获得实体 AIC。
    请求方需通过 mTLS 认证（使用本体证书）。
    """

    ontologyAic: str = Field(
        ...,
        min_length=1,
        description="本体 AIC（必填，指向所属本体）",
    )
    endPoints: Optional[List[EndPoint]] = Field(
        None,
        description="实体的服务端点列表（可选）。如果 Agent 对外提供 API 服务，实体需要有自己独立的服务端点。",
    )
    entityUserId: Optional[str] = Field(
        None,
        max_length=255,
        description="用于标识实体绑定的终端用户 ID（可选）",
    )
    entityMeta: Optional[dict] = Field(
        None,
        description="实体的额外元数据（可选）。可包含地理位置、环境信息、用户绑定关系等。",
    )

    @field_validator("ontologyAic")
    @classmethod
    def validate_ontology_aic_format(cls, v):
        """验证本体 AIC 格式：ACPs-spec-AIC-v02.00（点分10段 + CRC16）。"""
        v = v.strip()
        if not aic.validate_aic(v):
            raise ValueError("Invalid ontologyAic format")
        if not aic.is_ontology_aic(v):
            raise ValueError("ontologyAic must be an ontology AIC")
        return v


class EntityRegistrationResult(BaseModel):
    """
    实体注册结果（包含在响应的 result 字段中）
    """

    ontologyAic: str = Field(..., description="本体 AIC")
    entityAic: str = Field(..., description="新分配的实体 AIC")
    endPoints: Optional[List[EndPoint]] = Field(None, description="实体的服务端点列表")
    entityUserId: Optional[str] = Field(
        None,
        description="实体绑定的终端用户 ID（如果提供）",
    )
    entityMeta: Optional[dict] = Field(None, description="实体的额外元数据")


class EntityRegistrationError(BaseModel):
    """
    实体注册错误信息
    """

    code: int = Field(..., description="错误代码")
    message: str = Field(..., description="错误消息")
    data: Optional[dict] = Field(None, description="可选的错误数据")


class EntityRegistrationResponse(BaseModel):
    """
    实体注册响应模型（ATR-Registry-Server.md 规范）

    遵循 CommonResponse 结构，status 为 'ok' 时返回 result，
    status 为 'error' 时返回 error。
    """

    status: str = Field(
        ...,
        description="响应状态，可能的值包括 'ok' 和 'error'",
    )
    result: Optional[EntityRegistrationResult] = Field(
        None,
        description="方法调用的结果，如果调用成功则包含结果",
    )
    error: Optional[EntityRegistrationError] = Field(
        None,
        description="错误信息，如果调用失败则包含错误对象",
    )
