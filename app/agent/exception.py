from typing import Optional, Dict, Any

from app.core.base_exception import BaseException


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
    VECTOR_INDEX_FAILED = "vector_index_failed"
    VECTOR_CLIENT_NOT_INITIALIZED = "vector_client_not_initialized"
    LLM_CLIENT_NOT_INITIALIZED = "llm_client_not_initialized"
    EMBEDDING_GENERATION_FAILED = "embedding_generation_failed"
    INVALID_EMBEDDING_RESPONSE = "invalid_embedding_response"
    VECTOR_SEARCH_FAILED = "vector_search_failed"
    VECTOR_DELETE_FAILED = "vector_delete_failed"
    REMOTE_CERT_REVOKE_FAILED = "remote_cert_revoke_failed"
