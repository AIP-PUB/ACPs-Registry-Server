from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db_session import get_db
from app.agent.service import get_agent_by_aic, register_entity
from app.agent.schema import EntityRegistrationRequest, EntityRegistrationResponse
from app.agent.exception import AtrException, AtrErrorCode
from app.utils.aic import validate_aic, is_ontology_aic

# Create ATR router for Agent Trusted Registration protocol
router = APIRouter()

# -------------------------------------------------------------------
# ATR ENDPOINTS - Agent Trusted Registration API
# -------------------------------------------------------------------


@router.get("/acs/{agent_aic}")
async def get_agent_acs_by_aic(
    agent_aic: str,
    db: Session = Depends(get_db),
):
    """
    通过 AIC 获取 Agent 的 ACS 信息（ATR 协议接口）

    API 端点: GET {REGISTRY_SERVER_BASE_URL}/acs/{agent_aic}

    根据 ATR-Registry-Server.md 规范：
    - 200: 返回 AgentInfo（ACS 结构）
    - 404: agent_aic 对应的智能体不存在
    - 403: agent_aic 对应的智能体非 active 状态

    响应数据格式是ACS结构。
    """
    # 验证 AIC 格式
    if not validate_aic(agent_aic):
        raise AtrException(
            code=AtrErrorCode.INVALID_REQUEST,
            message="Invalid AIC format or checksum",
            http_status=status.HTTP_400_BAD_REQUEST,
            data={"agentAic": agent_aic},
        )

    # 根据 AIC 查询 Agent
    agent = get_agent_by_aic(db, agent_aic, raise_exception=False)
    if not agent:
        raise AtrException(
            code=AtrErrorCode.AGENT_NOT_FOUND,
            message="Agent not found with the provided AIC",
            http_status=status.HTTP_404_NOT_FOUND,
            data={"agentAic": agent_aic},
        )

    # 检查是否有 ACS 数据
    if not agent.acs:
        raise AtrException(
            code=AtrErrorCode.AGENT_ACS_MISSING,
            message="Agent ACS not found",
            http_status=status.HTTP_404_NOT_FOUND,
            data={"agentAic": agent_aic},
        )

    # ACS 现在是 JSONB 类型，直接使用 dict
    atr_response = agent.acs

    # 如果 Agent 不是 active 状态，返回 403 Forbidden
    if atr_response.get("active") is not True:
        raise AtrException(
            code=AtrErrorCode.AGENT_INACTIVE,
            message="Agent status is not active",
            http_status=status.HTTP_403_FORBIDDEN,
            data={
                "agentAic": agent_aic,
                "active": atr_response.get("active"),
            },
        )

    return JSONResponse(content=atr_response)


@router.post("/entity", response_model=EntityRegistrationResponse)
async def register_entity_endpoint(
    request: EntityRegistrationRequest,
    db: Session = Depends(get_db),
):
    """
    注册新的智能体实体（ATR 协议接口）

    API 端点: POST {REGISTRY_SERVER_BASE_URL}/entity

    根据 ATR-Registry-Server.md 规范：
    - 请求方通过 mTLS 认证（使用本体证书）
    - 本体 AIC 必须存在且处于 active 状态
    - 系统为新实体分配唯一的实体 AIC
    - 基于本体 ACS 和请求中的增量信息，创建实体 ACS

    请求体 (EntityRegistrationRequest):
    - ontologyAic: 本体 AIC（必填）
    - endPoints: 实体的服务端点列表（可选）
    - entityMeta: 实体的额外元数据（可选）

    响应体 (EntityRegistrationResponse):
    - status: "ok" | "error"
    - result: { ontologyAic, entityAic, endPoints, entityMeta }
    - error: { code, message, data } (仅当 status 为 "error" 时)

    响应码:
    - 201: 注册成功
    - 400: 请求参数格式错误或缺少必填字段
    - 401: mTLS 认证失败（证书无效或未提供）
    - 403: 本体已被禁用或吊销 / 实体数量已达配额上限
    - 404: 本体 AIC 不存在
    - 409: 服务端点 URL 与已有实体冲突
    """
    # 验证 ontologyAic 格式
    ontology_aic = request.ontologyAic.strip().upper()
    if not validate_aic(ontology_aic):
        raise AtrException(
            code=AtrErrorCode.INVALID_REQUEST,
            message="Invalid ontology AIC format or checksum",
            http_status=status.HTTP_400_BAD_REQUEST,
            data={"ontologyAic": ontology_aic},
        )

    # 验证是否为本体 AIC（实例序列号应为全 0；长度取决于 AIC 规范/实现）
    if not is_ontology_aic(ontology_aic):
        raise AtrException(
            code=AtrErrorCode.INVALID_REQUEST,
            message="The provided AIC is not an ontology AIC (instance serial should be all zeros)",
            http_status=status.HTTP_400_BAD_REQUEST,
            data={"ontologyAic": ontology_aic},
        )

    # 转换 endPoints 为字典列表（如果提供）
    end_points = None
    if request.endPoints:
        end_points = [ep.model_dump() for ep in request.endPoints]

    # 调用服务层进行实体注册
    result = register_entity(
        db=db,
        ontology_aic=ontology_aic,
        end_points=end_points,
        entity_meta=request.entityMeta,
        entity_user_id=request.entityUserId,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "status": "ok",
            "result": result,
        },
    )
