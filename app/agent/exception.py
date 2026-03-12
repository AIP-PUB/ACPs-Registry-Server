from enum import IntEnum
from typing import Optional, Dict, Any

from app.core.base_exception import BaseException
from app.core.acps_exception import AcpsException


class AgentException(BaseException):
    """
    Custom exception class for agent-related errors

    Inherits from BaseException but fixes error_group to 'agent'
    """

    def __init__(
        self,
        status_code: int = 400,
        error_name: str = "agent_error",
        error_msg: str = "An error occurred with agent operation",
        input_params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            status_code=status_code,
            error_group="agent",  # Fixed to 'agent' for all AgentExceptions
            error_name=error_name,
            error_msg=error_msg,
            input_params=input_params,
        )


class AgentError:
    """
    Class containing all agent error types as constants.
    This allows referencing error types using dot notation (AgentError.AGENT_NOT_FOUND)
    """

    AGENT_NOT_FOUND = "agent_not_found"
    INVALID_ACS = "invalid_acs"
    ACS_NOT_EXISTED = "acs_not_existed"
    AGENT_INACTIVE = "agent_inactive"
    AGENT_NAME_VERSION_EXISTS = "agent_name_version_exists"
    AGENT_NAME_ALREADY_CLAIMED = "agent_name_already_claimed"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    NON_APPROVED_AGENT_REQUIRES_AUTH = "non_approved_agent_requires_auth"
    ACCESS_DENIED_NOT_OWNER = "access_denied_not_owner"
    ACCESS_DENIED_OTHER_USER_AGENTS = "access_denied_other_user_agents"
    INVALID_STATUS_TRANSITION = "invalid_status_transition"
    PROCESSOR_NOT_FOUND = "processor_not_found"
    PROCESSOR_NOT_STAFF = "processor_not_staff"
    LLM_CLIENT_NOT_INITIALIZED = "llm_client_not_initialized"
    EMBEDDING_GENERATION_FAILED = "embedding_generation_failed"
    INVALID_EMBEDDING_RESPONSE = "invalid_embedding_response"
    REMOTE_CERT_REVOKE_FAILED = "remote_cert_revoke_failed"


class AtrErrorCode(IntEnum):
    """ATR protocol numeric error codes aligned with specification."""

    INVALID_REQUEST = 40001  # 请求参数格式错误或缺少必填字段
    UNAUTHORIZED = 40101  # mTLS 认证失败，证书无效或未提供
    ONTOLOGY_INACTIVE = 40302  # 本体已被禁用或吊销
    ENTITY_LIMIT_EXCEEDED = 40303  # 实体数量已达本体配额上限
    ONTOLOGY_NOT_FOUND = 40401  # 本体 AIC 不存在
    ENDPOINT_CONFLICT = 40901  # 服务端点 URL 与已有实体冲突

    # Additional ATR-specific codes for other scenarios
    AGENT_NOT_FOUND = 40410
    AGENT_INACTIVE = 40310
    AGENT_UNSUPPORTED = 40411
    AGENT_ACS_MISSING = 40412
    GENERATE_AIC_FAILED = 50001
    DATABASE_ERROR = 50002
    INTERNAL_ERROR = 50000


class AtrException(AcpsException):
    """Exception type dedicated to ATR protocol handlers."""

    def __init__(
        self,
        *,
        code: AtrErrorCode,
        message: str,
        http_status: int,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            protocol="atr",
            code=int(code),
            message=message,
            http_status=http_status,
            data=data,
        )
