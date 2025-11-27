from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db_session import get_db
from app.agent.service import get_agent_by_aic
from app.agent.exception import AgentException, AgentError

# Create ATR router for Agent Trusted Registration protocol
router = APIRouter()

# -------------------------------------------------------------------
# ATR ENDPOINTS - Agent Trusted Registration API
# -------------------------------------------------------------------


@router.get("/agent/{agent_aic}")
async def get_agent_acs_by_aic(
    agent_aic: str,
    db: Session = Depends(get_db),
):
    """
    通过 AIC 获取 Agent 的 ACS 信息（ATR 协议接口）

    API 端点: GET {REGISTRY_SERVER_BASE_URL}/agent/{agent_aic}

    响应数据格式是ACS结构。
    """
    # 根据 AIC 查询 Agent
    agent = get_agent_by_aic(db, agent_aic, raise_exception=True)

    # 检查 Agent 是否支持 ACP
    if not agent.is_acp_support:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent does not support ACP protocol",
            input_params={"agent_aic": agent_aic},
        )

    # 检查是否有 ACS 数据
    if not agent.acs:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent ACS not found",
            input_params={"agent_aic": agent_aic},
        )

    # 解析 ACS 数据并构造符合 ATR 规范的响应
    import json

    try:
        atr_response = json.loads(agent.acs)

        # 如果 Agent 不是 active 状态，返回 403 Forbidden
        if atr_response["active"] is not True:
            raise AgentException(
                status_code=status.HTTP_403_FORBIDDEN,
                error_name=AgentError.AGENT_NOT_FOUND,
                error_msg="Agent status is not active",
                input_params={"agent_aic": agent_aic, "active": atr_response["active"]},
            )

        return JSONResponse(content=atr_response)

    except json.JSONDecodeError:
        # 如果 JSON 解析失败，返回错误
        raise AgentException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent ACS data is corrupted",
            input_params={"agent_aic": agent_aic},
        )
