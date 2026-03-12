from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, status, Query, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db_session import get_db
from app.core.auth import get_current_user, check_user_role, safe_get_current_user
from app.account.model import User, RoleType
from app.agent.model import ApprovalStatus
from app.agent.schema import (
    AgentResponse,
    AgentDetailResponse,
    AgentListResponse,
    AgentCreate,
    AgentUpdate,
    AgentProcessRequest,
    AgentSearchQuery,
    AgentSearchResponse,
)
from app.agent.service import (
    get_agent,
    get_agents,
    create_agent,
    update_agent,
    submit_agent_for_approval,
    cancel_agent_submission,
    process_agent_approval,
    delete_agent,
    batch_delete_agents,
    disable_agent,
    enable_agent,
    get_recent_agents,
    create_agent_response,
    create_agent_detail_response,
    generate_jsonc_sample_from_schema,
    get_agent_by_aic,
)
from app.agent.exception import AgentException, AgentError
from app.utils.utils import parse_boolean_string
import json
import os
import logging

logger = logging.getLogger(__name__)

# Create separate routers for public, client and staff endpoints
router_public = APIRouter(prefix="/agent/public", tags=["agent-public"])
router_client = APIRouter(prefix="/agent/client", tags=["agent-client"])
router_staff = APIRouter(prefix="/agent/staff", tags=["agent-staff"])

# -------------------------------------------------------------------
# PUBLIC ENDPOINTS - No authentication required
# -------------------------------------------------------------------


@router_public.get("/acs_example")
async def get_acs_example():
    """
    获取 ACS (Agent Capability Spec) 的示例 JSONC (带注释)
    """
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    schema_path = os.path.join(base_dir, "app/agent/acsSchema.json")

    if not os.path.exists(schema_path):
        raise AgentException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name="schema_file_missing",
            error_msg="Schema file not found",
        )

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    jsonc_content, _ = generate_jsonc_sample_from_schema(schema)
    return jsonc_content


@router_public.get("/recent", response_model=AgentSearchResponse)
async def public_get_recent_approved_agents(
    limit: int = 5, with_users: bool = False, db: Session = Depends(get_db)
):
    """
    获取最近审批通过的 Agent，默认 5 条（公开接口，无需登录）
    - 支持是否加载关联用户数据（创建者和处理者）
    """
    # 将 with_users 参数传递给 get_recent_agents 函数
    agents = get_recent_agents(db, limit, with_users=with_users)

    # 根据是否加载了用户信息，选择合适的响应构造函数
    if with_users:
        items = [create_agent_detail_response(agent) for agent in agents]
    else:
        items = [create_agent_response(agent) for agent in agents]

    total = len(items)
    return {
        "items": items,
        "total": total,
        "page_num": 1,
        "page_size": limit,
    }


@router_public.get("/{agent_id}", response_model=AgentDetailResponse)
async def public_read_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    公开获取已审批通过的 Agent 详情。
    仅返回已审批通过的 Agent，未审批通过的需使用 client 或 staff 接口。
    """
    # 详情接口加载完整的用户信息
    agent = get_agent(db, agent_id, with_users=True, raise_exception=True)

    # 公开接口只能访问已审批通过的 Agent
    if agent.approval_status != ApprovalStatus.APPROVED:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent not found or not approved",
            input_params={"agent_id": str(agent_id)},
        )

    return create_agent_detail_response(agent)


# -------------------------------------------------------------------
# CLIENT ENDPOINTS - Requires CLIENT role only (not STAFF or ADMIN)
# -------------------------------------------------------------------


@router_client.get("/{agent_id}", response_model=AgentDetailResponse)
async def client_read_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    客户端获取 Agent 详情。
    已审批通过的 Agent 或用户自己创建的 Agent 可以访问。
    仅限 CLIENT 角色访问，STAFF 和 ADMIN 角色不可访问。
    """
    # 详情接口加载完整的用户信息
    agent = get_agent(db, agent_id, with_users=True, raise_exception=True)

    # 已审批通过的 agent 可以访问
    if agent.approval_status == ApprovalStatus.APPROVED:
        return create_agent_detail_response(agent)

    # 未审批通过的 agent 仅限本人访问
    if agent.created_by_id != current_user.id:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.ACCESS_DENIED_NOT_OWNER,
            error_msg="Access denied: you can only view non-approved agents that you created",
            input_params={
                "agent_id": str(agent_id),
                "request_user_id": str(current_user.id),
            },
        )

    return create_agent_detail_response(agent)


@router_client.post("", response_model=AgentResponse)
async def client_create_new_agent(
    agent_create: AgentCreate,
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
    db: Session = Depends(get_db),
):
    """
    创建新 Agent，保存但不提交审核（仅限 CLIENT 角色）
    """
    agent = create_agent(db, current_user.id, agent_create.dict())
    # 不需要加载用户信息
    agent = get_agent(db, agent.id, with_users=False)
    return create_agent_response(agent)


@router_client.get("", response_model=AgentListResponse)
async def client_read_agents(
    statuses: List[ApprovalStatus] = Query(None, explode=True),
    name: Optional[str] = None,
    version: Optional[str] = None,
    aic: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    is_active: Optional[str] = Query(None),
    is_deleted: Optional[str] = Query(None),
    is_disabled: Optional[str] = Query(None),
    with_users: bool = False,
    is_ontology: Optional[bool] = None,
    page_num: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    获取当前用户的 Agent 列表，普通用户只能查看自己的 Agent
    - 支持按多个状态、名称、版本和协议支持情况过滤
    - 支持是否加载关联用户数据（创建者和处理者）
    - 包含被工作人员禁用但未删除的 Agent
    - 仅限 CLIENT 角色访问
    """
    # 普通用户只能查看自己的 Agent
    create_by_id = current_user.id

    # 将字符串类型的布尔查询参数转换为布尔值或 None
    is_active_bool = parse_boolean_string(is_active)
    is_deleted_bool = parse_boolean_string(is_deleted)
    is_disabled_bool = parse_boolean_string(is_disabled)

    agents, total = get_agents(
        db=db,
        page_num=page_num,
        page_size=page_size,
        statuses=statuses,
        name=name,
        version=version,
        aic=aic,
        name_like=name_like,
        version_like=version_like,
        aic_like=aic_like,
        create_by_id=create_by_id,
        with_users=with_users,
        is_active=is_active_bool,
        is_deleted=is_deleted_bool,
        is_disabled=is_disabled_bool,
        is_ontology=is_ontology,
    )

    # 根据是否加载了用户信息，选择合适的响应构造函数
    if with_users:
        items = [create_agent_detail_response(agent) for agent in agents]
    else:
        items = [create_agent_response(agent) for agent in agents]

    return {
        "items": items,
        "total": total,
        "page_num": page_num,
        "page_size": page_size,
    }


@router_client.put("/{agent_id}", response_model=AgentResponse)
async def client_update_agent_info(
    agent_id: uuid.UUID,
    agent_update: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    更新 Agent，审核通过的不能再更新（仅限 CLIENT 角色）
    """
    updated_agent = update_agent(
        db, agent_id, current_user.id, agent_update.dict(exclude_unset=True)
    )
    if agent_update.acs is None:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.ACS_NOT_EXISTED,
            error_msg="ACS cannot be null",
            input_params={"agent_id": str(agent_id)},
        )
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)


@router_client.post("/{agent_id}/submit", response_model=AgentResponse)
async def client_submit_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    提交 Agent 进行审核（仅限 CLIENT 角色）
    """
    agent = submit_agent_for_approval(db, agent_id, current_user.id)
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)


@router_client.post("/{agent_id}/cancel", response_model=AgentResponse)
async def client_cancel_agent_submission_request(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    撤销处于"审核中"状态的 Agent 申请（仅限 CLIENT 角色）
    """
    agent = cancel_agent_submission(db, agent_id, current_user.id)
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)


@router_client.delete("/{agent_id}", response_model=dict)
async def client_delete_agent_record(
    agent_id: uuid.UUID,
    reason: str = Body("User deletion", description="删除原因"),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    删除 Agent（仅限 CLIENT 角色）
    """
    success = delete_agent(db, agent_id, current_user.id, reason)
    return {"message": "Agent deleted successfully"}


@router_client.delete("", response_model=dict)
async def client_delete_multiple_agents(
    agent_ids: List[uuid.UUID] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.CLIENT])),
):
    """
    批量删除 Agent（仅限 CLIENT 角色）
    """
    results = batch_delete_agents(db, agent_ids, current_user.id)
    return results


# -------------------------------------------------------------------
# STAFF ENDPOINTS - Requires STAFF role
# -------------------------------------------------------------------


@router_staff.get("/{agent_id}", response_model=AgentDetailResponse)
async def staff_read_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.STAFF, RoleType.ADMIN])),
):
    """
    工作人员获取 Agent 详情。工作人员可以查看任何 Agent。
    """
    # 详情接口加载完整的用户信息
    agent = get_agent(db, agent_id, with_users=True, raise_exception=True)
    return create_agent_detail_response(agent)


@router_staff.get("", response_model=AgentListResponse)
async def staff_read_agents(
    statuses: List[ApprovalStatus] = Query(None, explode=True),
    name: Optional[str] = None,
    version: Optional[str] = None,
    aic: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    is_active: Optional[str] = Query(None),
    is_deleted: Optional[str] = Query(None),
    is_disabled: Optional[str] = Query(None),
    create_by_id: Optional[uuid.UUID] = None,
    process_by_id: Optional[uuid.UUID] = None,
    processed_by_me: Optional[bool] = False,
    with_users: bool = False,
    page_num: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.STAFF, RoleType.ADMIN])),
):
    """
    工作人员获取 Agent 列表，工作人员可查看所有 Agent
    - 支持按多个状态、名称、版本和协议支持情况过滤
    - 支持按创建者和处理者过滤
    - 支持是否加载关联用户数据（创建者和处理者）
    """
    # 将字符串类型的布尔查询参数转换为布尔值或 None
    is_active_bool = parse_boolean_string(is_active)
    is_deleted_bool = parse_boolean_string(is_deleted)
    is_disabled_bool = parse_boolean_string(is_disabled)

    # 如果 processed_by_me 为 True，则将 process_by_id 设置为当前用户的 ID
    if processed_by_me:
        process_by_id = current_user.id

    agents, total = get_agents(
        db=db,
        page_num=page_num,
        page_size=page_size,
        statuses=statuses,
        name=name,
        version=version,
        aic=aic,
        name_like=name_like,
        version_like=version_like,
        aic_like=aic_like,
        create_by_id=create_by_id,
        process_by_id=process_by_id,
        with_users=with_users,
        is_active=is_active_bool,
        is_deleted=is_deleted_bool,
        is_disabled=is_disabled_bool,
    )

    # 根据是否加载了用户信息，选择合适的响应构造函数
    if with_users:
        items = [create_agent_detail_response(agent) for agent in agents]
    else:
        items = [create_agent_response(agent) for agent in agents]

    return {
        "items": items,
        "total": total,
        "page_num": page_num,
        "page_size": page_size,
    }


@router_staff.post("/{agent_id}/process", response_model=AgentResponse)
async def staff_process_agent(
    agent_id: uuid.UUID,
    request: AgentProcessRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.STAFF, RoleType.ADMIN])),
):
    """
    审核 Agent，设置通过/驳回及审核意见（仅 staff）
    """
    agent = process_agent_approval(
        db, agent_id, current_user.id, request.approve, request.comments
    )
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)


@router_staff.post("/{agent_id}/disable", response_model=AgentResponse)
async def staff_disable_agent(
    agent_id: uuid.UUID,
    reason: str = Body("Staff disable", description="禁用原因"),
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.STAFF, RoleType.ADMIN])),
):
    """
    禁用 Agent（仅限 STAFF 角色）
    """
    agent = disable_agent(db, agent_id, current_user.id, reason)
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)


@router_staff.post("/{agent_id}/enable", response_model=AgentResponse)
async def staff_enable_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_user_role([RoleType.STAFF, RoleType.ADMIN])),
):
    """
    启用被禁用的 Agent（仅限 STAFF 角色）
    """
    agent = enable_agent(db, agent_id, current_user.id)
    agent = get_agent(db, agent_id, with_users=False)
    return create_agent_response(agent)
