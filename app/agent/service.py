from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
import uuid
import time
import requests
import logging
from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy.orm import Session, joinedload
from fastapi import status

from app.agent.model import Agent, ApprovalStatus
from app.agent.schema import AgentResponse, AgentDetailResponse
from app.account.schema_account import UserResponse
from app.sync.service import create_change_log
from app.agent.service_vector import (
    index_agent,
    search_agents_by_vector,
    delete_agent_from_vector,
)
from app.agent.exception import AgentException, AgentError
from app.sync.service import (
    trigger_data_change_webhook,
    trigger_retention_cleanup_webhook,
)
from app.utils.utils import get_beijing_time, utc_to_beijing, beijing_to_utc, sha256
from app.utils import aic
from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)


def create_agent_response(agent: Agent) -> AgentResponse:
    """将 Agent ORM 对象转换为 AgentResponse"""
    if not agent:
        return None

    # 使用 model_validate 替代 from_orm
    return AgentResponse.model_validate(agent)


def create_agent_detail_response(agent: Agent) -> AgentDetailResponse:
    """将 Agent ORM 对象转换为包含完整用户对象的 AgentDetailResponse"""
    if not agent:
        return None

    # 先创建基本 AgentResponse
    response = AgentResponse.model_validate(agent)

    # 创建详情响应对象并继承基本响应的所有字段
    detail_response = AgentDetailResponse(**response.model_dump())

    # 添加完整用户对象
    if agent.created_by:
        detail_response.created_by = UserResponse.model_validate(agent.created_by)

    if agent.processed_by:
        detail_response.processed_by = UserResponse.model_validate(agent.processed_by)

    return detail_response


def get_agent(
    db: Session,
    agent_id: uuid.UUID,
    with_users: bool = True,
    raise_exception: bool = False,
) -> Optional[Agent]:
    """
    获取 Agent 详情

    Args:
        db: 数据库会话
        agent_id: Agent ID
        with_users: 是否加载关联的用户信息
        raise_exception: 是否在未找到时抛出异常 (default: False)

    Returns:
        Agent 对象, 如果未找到且 raise_exception=False 则返回 None

    Raises:
        AgentException: 如果未找到且 raise_exception=True
    """
    query = db.query(Agent).filter(Agent.id == agent_id)

    # 只有在需要详情视图时才加载关联用户
    if with_users:
        query = query.options(
            joinedload(Agent.created_by), joinedload(Agent.processed_by)
        )

    agent = query.first()

    if not agent and raise_exception:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent not found",
            input_params={"agent_id": str(agent_id)},
        )

    return agent


def get_agent_by_aic(
    db: Session,
    agent_aic: str,
    raise_exception: bool = False,
) -> Optional[Agent]:
    """
    根据 AIC 获取 Agent 详情

    Args:
        db: 数据库会话
        agent_aic: Agent Identity Code (AIC)
        raise_exception: 是否在未找到时抛出异常 (default: False)

    Returns:
        Agent 对象, 如果未找到且 raise_exception=False 则返回 None

    Raises:
        AgentException: 如果未找到且 raise_exception=True
    """
    # 根据 AIC 查找 Agent，不限制状态
    agent = db.query(Agent).filter(Agent.aic == agent_aic).first()

    if not agent and raise_exception:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.AGENT_NOT_FOUND,
            error_msg="Agent not found with the provided AIC",
            input_params={"agent_aic": agent_aic},
        )

    return agent


def update_agent_acs_data(agent: Agent, db: Session = None) -> None:
    """
    更新Agent的acs数据，确保其中包含正确的aic、active和lastModifiedTime字段
    如果ACS数据发生变化，会触发同步机制创建ChangeLog

    Args:
        agent: Agent对象
        db: 数据库会话（可选，如果提供则会在ACS变化时创建ChangeLog）
    """
    import json

    if not agent.acs:
        return

    is_acs_changed = False
    original_acs = agent.acs

    try:
        # 解析 ACS JSON
        acs_data = json.loads(agent.acs)

        if isinstance(acs_data, dict):
            # 检查并更新aic字段（小写）
            if agent.aic and acs_data.get("aic") != agent.aic:
                acs_data["aic"] = agent.aic
                is_acs_changed = True

            # 检查并更新active字段（布尔值）
            expected_active = agent.is_active
            if acs_data.get("active") != expected_active:
                acs_data["active"] = expected_active
                is_acs_changed = True

            # 如果有变化，更新agent.acs
            if is_acs_changed:
                # 添加lastModifiedTime字段（北京时间带时区，ISO格式）
                current_time = get_beijing_time()
                acs_data["lastModifiedTime"] = current_time.isoformat()
                agent.acs = json.dumps(acs_data, ensure_ascii=False)

    except json.JSONDecodeError:
        # 如果JSON解析失败，不进行更新
        return

    # 如果ACS发生了变化且提供了数据库会话，则调用同步函数
    if is_acs_changed and db is not None:
        from app.sync.service import update_agent_with_changelog

        # 准备仅包含acs的agent_data，让update_agent_with_changelog处理同步相关字段
        agent_data = {"acs": agent.acs}

        try:
            # 调用同步函数，传入agent对象而不是agent_id
            update_agent_with_changelog(db, agent, agent_data)
        except Exception as e:
            # 如果同步失败，恢复原始ACS数据
            agent.acs = original_acs
            raise e


def get_agents(
    db: Session,
    page_num: int = 1,
    page_size: int = 10,
    statuses: Optional[List[ApprovalStatus]] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    is_acp_support: Optional[bool] = None,
    is_a2a_support: Optional[bool] = None,
    is_anp_support: Optional[bool] = None,
    create_by_id: Optional[uuid.UUID] = None,
    process_by_id: Optional[uuid.UUID] = None,
    with_users: bool = False,
    include_inactive: bool = False,
    include_deleted: bool = False,
) -> Tuple[List[Agent], int]:
    """获取 Agent 列表，带过滤和分页

    Args:
        db: 数据库会话
        page_num: 页码，从1开始
        page_size: 每页数量
        statuses: 按审批状态过滤，支持多个状态
        name: 按名称模糊匹配
        version: 按版本模糊匹配
        is_acp_support: 按是否支持ACP协议过滤
        is_a2a_support: 按是否支持A2A协议过滤
        is_anp_support: 按是否支持ANP协议过滤
        create_by_id: 按创建者ID过滤
        process_by_id: 按处理人ID过滤
        with_users: 是否加载关联的用户信息
        include_inactive: 是否包含被禁用的 Agent (默认不包含)
        include_deleted: 是否包含已删除的 Agent (默认不包含)
    """
    # 基础查询
    query = db.query(Agent)

    if not include_inactive:
        query = query.filter(Agent.is_active == True)

    if not include_deleted:
        query = query.filter(Agent.is_deleted == False)

    # 如果需要加载关联用户
    if with_users:
        query = query.options(
            joinedload(Agent.created_by), joinedload(Agent.processed_by)
        )

    # 应用过滤条件
    if create_by_id:
        query = query.filter(Agent.created_by_id == create_by_id)
    if process_by_id:
        query = query.filter(Agent.processed_by_id == process_by_id)

    # 支持多状态查询
    if statuses:
        query = query.filter(Agent.approval_status.in_(statuses))

    # 模糊匹配名称
    if name:
        query = query.filter(Agent.name.ilike(f"%{name}%"))

    # 模糊匹配版本
    if version:
        query = query.filter(Agent.version.ilike(f"%{version}%"))

    # 按协议支持情况过滤
    if is_acp_support is not None:
        query = query.filter(Agent.is_acp_support == is_acp_support)

    if is_a2a_support is not None:
        query = query.filter(Agent.is_a2a_support == is_a2a_support)

    if is_anp_support is not None:
        query = query.filter(Agent.is_anp_support == is_anp_support)

    # 获取总数
    total = query.count()

    # 计算分页偏移量
    skip = (page_num - 1) * page_size

    # 应用分页和排序
    agents = query.order_by(Agent.created_at.desc()).offset(skip).limit(page_size).all()

    return agents, total


def create_agent(db: Session, user_id: uuid.UUID, agent_data: Dict[str, Any]) -> Agent:
    """Create a new agent in draft status"""
    # 首先检查是否有其他用户已经使用了相同的名称
    name_owner = (
        db.query(Agent)
        .filter(
            Agent.name == agent_data["name"],
            Agent.is_active == True,
            Agent.created_by_id != user_id,  # 检查是否有其他用户拥有该名称
        )
        .first()
    )

    if name_owner:
        # 如果其他用户已经使用了这个名称，不允许创建
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.AGENT_NAME_ALREADY_CLAIMED,
            error_msg=f"The name '{agent_data['name']}' is already owned by another user. Please choose a different name.",
            input_params={"name": agent_data["name"]},
        )

    # 检查具有相同 name 和 version 的 Agent 是否已存在
    existing_agent = (
        db.query(Agent)
        .filter(
            Agent.name == agent_data["name"],
            Agent.version == agent_data["version"],
            Agent.is_active == True,  # 只检查活跃的 Agent
        )
        .first()
    )

    if existing_agent:
        raise AgentException(
            status_code=status.HTTP_409_CONFLICT,
            error_name=AgentError.AGENT_NAME_VERSION_EXISTS,
            error_msg=f"Agent with name '{agent_data['name']}' and version '{agent_data['version']}' already exists",
            input_params={"name": agent_data["name"], "version": agent_data["version"]},
        )

    # Calculate acs_hash if acs is provided
    if agent_data.get("acs"):
        agent_data["acs_hash"] = sha256(agent_data["acs"])

    # Create agent with user as creator - 使用北京时间
    agent = Agent(
        **agent_data,
        created_by_id=user_id,
        approval_status=ApprovalStatus.DRAFT,
        created_at=get_beijing_time(),
        updated_at=get_beijing_time(),
    )

    try:
        db.add(agent)
        db.commit()
        db.refresh(agent)

        return agent
    except Exception as e:
        db.rollback()
        # 捕获数据库唯一性约束冲突
        if "uq_agent_name_version" in str(e):
            raise AgentException(
                status_code=status.HTTP_409_CONFLICT,
                error_name=AgentError.AGENT_NAME_VERSION_EXISTS,
                error_msg=f"Agent with name '{agent_data['name']}' and version '{agent_data['version']}' already exists",
                input_params={
                    "name": agent_data["name"],
                    "version": agent_data["version"],
                },
            )
        raise e


def update_agent(
    db: Session, agent_id: uuid.UUID, user_id: uuid.UUID, agent_data: Dict[str, Any]
) -> Agent:
    """Update an agent (only in draft status)"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # Ensure agent is active
    if not agent.is_active:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.AGENT_INACTIVE,
            error_msg="Cannot update an inactive agent",
            input_params={"agent_id": str(agent_id)},
        )

    # Ensure user is the creator of the agent
    if agent.created_by_id != user_id:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.UNAUTHORIZED_ACCESS,
            error_msg="You can only update your own agents",
            input_params={"agent_id": str(agent_id), "user_id": str(user_id)},
        )

    # Agent，审核通过或正在审核中的都不能再更新
    if agent.approval_status in [ApprovalStatus.APPROVED, ApprovalStatus.PENDING]:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.INVALID_STATUS_TRANSITION,
            error_msg=f"Agents in {agent.approval_status} status cannot be updated",
            input_params={"agent_id": str(agent_id), "status": agent.approval_status},
        )

    # 检查名称或版本是否更改，如果更改了，需要检查唯一性
    if ("name" in agent_data and agent_data["name"] != agent.name) or (
        "version" in agent_data and agent_data["version"] != agent.version
    ):
        # 获取新的名称和版本（如果未提供则使用现有值）
        new_name = agent_data.get("name", agent.name)
        new_version = agent_data.get("version", agent.version)

        # 检查具有相同名称和版本的其他 Agent 是否存在
        existing_agent = (
            db.query(Agent)
            .filter(
                Agent.name == new_name,
                Agent.version == new_version,
                Agent.id != agent_id,  # 排除当前 Agent
                Agent.is_active == True,
            )
            .first()
        )

        if existing_agent:
            raise AgentException(
                status_code=status.HTTP_409_CONFLICT,
                error_name=AgentError.AGENT_NAME_VERSION_EXISTS,
                error_msg=f"Agent with name '{new_name}' and version '{new_version}' already exists",
                input_params={"name": new_name, "version": new_version},
            )

    try:
        # 如果更新了ACS数据，需要触发同步机制
        acs_updated = False
        if "acs" in agent_data:
            # Calculate acs_hash
            new_acs_hash = sha256(agent_data["acs"])
            agent_data["acs_hash"] = new_acs_hash

            # 检查ACS是否真的发生了变化
            if new_acs_hash != agent.acs_hash:
                acs_updated = True

        # 直接更新agent对象的字段
        for key, value in agent_data.items():
            if hasattr(agent, key):
                setattr(agent, key, value)

        # 更新时间戳
        agent.updated_at = get_beijing_time()

        # 如果ACS数据发生了变化，触发同步机制
        if acs_updated:
            from app.sync.service import update_agent_with_changelog

            # 准备同步数据（只包含acs）
            sync_data = {"acs": agent.acs}
            update_agent_with_changelog(db, agent, sync_data)
        else:
            # 即使没有ACS变化，也要确保ACS数据中的aic和active字段正确
            update_agent_acs_data(agent, db)

        db.add(agent)
        db.commit()
        db.refresh(agent)
        return agent
    except Exception as e:
        db.rollback()
        # 捕获数据库唯一性约束冲突
        if "uq_agent_name_version" in str(e):
            # 获取冲突的名称和版本
            name = agent_data.get("name", agent.name)
            version = agent_data.get("version", agent.version)
            raise AgentException(
                status_code=status.HTTP_409_CONFLICT,
                error_name=AgentError.AGENT_NAME_VERSION_EXISTS,
                error_msg=f"Agent with name '{name}' and version '{version}' already exists",
                input_params={"name": name, "version": version},
            )
        raise e


def submit_agent_for_approval(
    db: Session, agent_id: uuid.UUID, user_id: uuid.UUID
) -> Agent:
    """Submit an agent for review"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # Ensure agent is active
    if not agent.is_active:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.AGENT_INACTIVE,
            error_msg="Cannot update an inactive agent",
            input_params={"agent_id": str(agent_id)},
        )
    # Ensure user is the creator of the agent
    if agent.created_by_id != user_id:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.UNAUTHORIZED_ACCESS,
            error_msg="You can only submit your own agents for review",
            input_params={"agent_id": str(agent_id), "user_id": str(user_id)},
        )

    # Ensure agent is in draft status, or rejected status
    if (
        agent.approval_status != ApprovalStatus.DRAFT
        and agent.approval_status != ApprovalStatus.REJECTED
    ):
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.INVALID_STATUS_TRANSITION,
            error_msg="Only agents in draft or rejected status can be submitted for review",
            input_params={"agent_id": str(agent_id), "status": agent.approval_status},
        )

    # Update status and submission time - using Beijing time
    agent.approval_status = ApprovalStatus.PENDING
    agent.submitted_at = get_beijing_time()
    agent.updated_at = get_beijing_time()

    db.add(agent)
    db.commit()
    db.refresh(agent)

    return agent


def cancel_agent_submission(
    db: Session, agent_id: uuid.UUID, user_id: uuid.UUID
) -> Agent:
    """Cancel a pending agent submission"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # Ensure agent is active
    if not agent.is_active:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.AGENT_INACTIVE,
            error_msg="Cannot update an inactive agent",
            input_params={"agent_id": str(agent_id)},
        )
    # Ensure user is the creator of the agent
    if agent.created_by_id != user_id:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.UNAUTHORIZED_ACCESS,
            error_msg="You can only cancel your own agent submissions",
            input_params={"agent_id": str(agent_id), "user_id": str(user_id)},
        )

    # Ensure agent is in pending status
    if agent.approval_status != ApprovalStatus.PENDING:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.INVALID_STATUS_TRANSITION,
            error_msg="Only agents in pending status can be canceled",
            input_params={"agent_id": str(agent_id), "status": agent.approval_status},
        )

    # Update status back to draft - using Beijing time
    agent.approval_status = ApprovalStatus.DRAFT
    agent.submitted_at = None
    agent.updated_at = get_beijing_time()

    db.add(agent)
    db.commit()
    db.refresh(agent)

    return agent


def process_agent_approval(
    db: Session,
    agent_id: uuid.UUID,
    processor_id: uuid.UUID,
    approve: bool,
    comments: Optional[str] = None,
) -> Agent:
    """Process an agent approval request (approve or reject)"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # Ensure agent is active
    if not agent.is_active:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.AGENT_INACTIVE,
            error_msg="Cannot update an inactive agent",
            input_params={"agent_id": str(agent_id)},
        )

    # 检查处理人是否具有STAFF角色
    from app.account.model import User, RoleType

    processor = db.query(User).filter(User.id == processor_id).first()
    if not processor:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.PROCESSOR_NOT_FOUND,
            error_msg="Processor not found",
            input_params={"processor_id": str(processor_id)},
        )

    has_staff_role = any(role.name == RoleType.STAFF for role in processor.roles)
    if not has_staff_role:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.PROCESSOR_NOT_STAFF,
            error_msg="Only users with STAFF role can process agent approvals",
            input_params={"processor_id": str(processor_id)},
        )

    # Ensure agent is in pending status
    if agent.approval_status != ApprovalStatus.PENDING:
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.INVALID_STATUS_TRANSITION,
            error_msg="Only agents in pending status can be processed",
            input_params={"agent_id": str(agent_id), "status": agent.approval_status},
        )

    # If approving, first try to index the agent to ensure it can be indexed
    # We do this before making any database changes
    vector_id = None
    if approve:
        try:
            vector_id = index_agent(agent)
            if vector_id is None:
                raise AgentException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    error_name=AgentError.VECTOR_INDEX_FAILED,
                    error_msg="Failed to index agent in vector database. Approval process aborted.",
                    input_params={"agent_id": str(agent_id)},
                )
        except Exception as e:
            raise AgentException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=AgentError.VECTOR_INDEX_FAILED,
                error_msg=f"Failed to index agent in vector database: {str(e)}. Approval process aborted.",
                input_params={"agent_id": str(agent_id)},
            )

    # Update status based on approval decision - using Beijing time
    agent.approval_status = (
        ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    )
    agent.processed_by_id = processor_id
    agent.processed_at = get_beijing_time()
    agent.process_comments = comments
    agent.updated_at = get_beijing_time()

    # If approved, save the vector_id from the successful indexing
    if approve and vector_id:
        agent.vector_id = vector_id

    db.add(agent)
    db.commit()
    db.refresh(agent)

    # generate AIC(Agent Identity Code) for the agent
    if approve and not agent.aic:
        generate_aic_for_agent(db, agent)

    return agent


def generate_aic_for_agent(db: Session, agent: Agent) -> Agent:
    """
    Generate a unique AIC (Agent Identifier Code) for an agent.
    If commit fails, retry up to 3 times with a 2ms delay between retries.

    Args:
        db: Database session
        agent: Agent object

    Returns:
        Agent object with AIC generated

    Raises:
        SQLAlchemyError: If commit fails after 3 retries
    """
    # Ensure agent is in approved status
    if agent.approval_status != ApprovalStatus.APPROVED:
        return agent

    # Check if AIC already exists
    if agent.aic:
        return agent

    # Retry logic for commit operation
    max_retries = 3
    retry_count = 0
    retry_delay = 0.002  # 2 milliseconds

    while retry_count < max_retries:
        try:
            # Generate AIC if not already generated
            agent.aic = aic.generate_aic()
            # Update timestamp with Beijing time
            agent.updated_at = get_beijing_time()

            # 更新Agent的acs数据
            update_agent_acs_data(agent, db)

            db.add(agent)
            db.commit()
            db.refresh(agent)
            return agent
        except SQLAlchemyError as e:
            retry_count += 1
            # If we've reached max retries, raise the exception
            if retry_count >= max_retries:
                raise e
            # Otherwise, rollback and retry after delay
            db.rollback()
            time.sleep(retry_delay)

    # This should never be reached due to the exception in the loop
    return agent


def delete_agent(
    db: Session, agent_id: uuid.UUID, user_id: uuid.UUID, reason: str = "User deletion"
) -> bool:
    """Delete an agent (owner only)"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # Ensure user is the creator of the agent
    if agent.created_by_id != user_id:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.UNAUTHORIZED_ACCESS,
            error_msg="You can only delete your own agents",
            input_params={"agent_id": str(agent_id), "user_id": str(user_id)},
        )

    # Soft delete - mark as inactive and deleted - using Beijing time
    current_time = get_beijing_time()
    old_status = "active" if agent.is_active else "inactive"
    agent.is_active = False
    agent.is_deleted = True
    agent.deleted_at = current_time
    agent.deleted_reason = reason
    agent.updated_at = current_time

    # 更新Agent的acs数据
    update_agent_acs_data(agent, db)

    # 通知 CA Server 吊销证书（使用 ATR 协议）
    notify_ca_server_revoke_cert(agent, reason=5)  # cessationOfOperation
    # 更新数据库
    db.add(agent)
    db.commit()

    # trigger_webhook_03
    try:
        trigger_data_change_webhook(db, ["acs"])
    except Exception as e:
        # 记录错误但不影响主流程
        print(f"Failed to trigger webhook for agent deletion: {str(e)}")

    # Remove from vector database if it was indexed
    if agent.vector_id:
        try:
            delete_agent_from_vector(agent.vector_id)
        except Exception as e:
            # Log but don't fail if vector deletion fails
            # Vector database is eventually consistent
            pass

    return True


def batch_delete_agents(
    db: Session, agent_ids: List[uuid.UUID], user_id: uuid.UUID
) -> Dict[str, Any]:
    """Batch delete multiple agents"""
    results = {"success": [], "failed": []}

    for agent_id in agent_ids:
        try:
            delete_agent(db, agent_id, user_id, reason="Batch Delete")
            results["success"].append(str(agent_id))
        except Exception as e:
            results["failed"].append({"id": str(agent_id), "reason": str(e)})

    return results


def disable_agent(
    db: Session,
    agent_id: uuid.UUID,
    staff_user_id: uuid.UUID,
    reason: str = "Staff disable",
) -> Agent:
    """Disable an agent (staff only)"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # 检查处理人是否具有STAFF角色
    from app.account.model import User, RoleType

    staff_user = db.query(User).filter(User.id == staff_user_id).first()
    if not staff_user:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.PROCESSOR_NOT_FOUND,
            error_msg="Staff user not found",
            input_params={"staff_user_id": str(staff_user_id)},
        )

    has_staff_role = any(role.name == RoleType.STAFF for role in staff_user.roles)
    if not has_staff_role:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.PROCESSOR_NOT_STAFF,
            error_msg="Only users with STAFF role can disable agents",
            input_params={"staff_user_id": str(staff_user_id)},
        )

    # 禁用Agent - using Beijing time
    current_time = get_beijing_time()
    old_status = "active" if agent.is_active else "inactive"
    agent.is_active = False
    agent.is_disabled = True
    agent.disabled_at = current_time
    agent.disabled_reason = reason
    agent.updated_at = current_time

    # 更新Agent的acs数据
    update_agent_acs_data(agent, db)

    # 通知 CA Server 吊销证书（使用 ATR 协议）
    notify_ca_server_revoke_cert(agent, reason=5)  # cessationOfOperation

    # 更新数据库
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # trigger_webhook_02
    create_change_log(db, "acs", agent.aic, agent.acs_version, agent.acs)
    db.commit()
    db.refresh(agent)
    trigger_data_change_webhook(db, ["acs"])

    return agent


def enable_agent(db: Session, agent_id: uuid.UUID, staff_user_id: uuid.UUID) -> Agent:
    """Enable a disabled agent (staff only)"""
    agent = get_agent(db, agent_id, raise_exception=True)

    # 检查处理人是否具有STAFF角色
    from app.account.model import User, RoleType

    staff_user = db.query(User).filter(User.id == staff_user_id).first()
    if not staff_user:
        raise AgentException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_name=AgentError.PROCESSOR_NOT_FOUND,
            error_msg="Staff user not found",
            input_params={"staff_user_id": str(staff_user_id)},
        )

    has_staff_role = any(role.name == RoleType.STAFF for role in staff_user.roles)
    if not has_staff_role:
        raise AgentException(
            status_code=status.HTTP_403_FORBIDDEN,
            error_name=AgentError.PROCESSOR_NOT_STAFF,
            error_msg="Only users with STAFF role can enable agents",
            input_params={"staff_user_id": str(staff_user_id)},
        )

    # 启用Agent - using Beijing time
    current_time = get_beijing_time()
    old_status = "inactive" if not agent.is_active else "active"
    agent.is_disabled = False
    agent.disabled_at = None
    agent.disabled_reason = None
    agent.updated_at = current_time

    # 如果Owner未删除，则激活
    if agent.is_deleted is False:
        agent.is_active = True

    # 更新Agent的acs数据
    update_agent_acs_data(agent, db)

    # 提示：远程证书没有激活的能力，需要重新申请新证书。

    db.add(agent)
    db.commit()
    db.refresh(agent)

    # trigger_webhook_01
    create_change_log(db, "acs", agent.aic, agent.acs_version, agent.acs)
    db.commit()
    db.refresh(agent)
    trigger_data_change_webhook(db, ["acs"])

    return agent


def notify_ca_server_revoke_cert(agent: Agent, reason: int = 5):
    """
    通知 CA Server 吊销指定 Agent 的证书（使用 ATR 协议）

    Args:
        agent: Agent对象，需要包含AIC
        reason: 吊销原因代码，默认为5 (cessationOfOperation)
               - 0: unspecified（未指定）
               - 1: keyCompromise（密钥泄露）
               - 2: cACompromise（CA 泄露）
               - 3: affiliationChanged（隶属关系变更）
               - 4: superseded（被替代）
               - 5: cessationOfOperation（停止运营）
    """
    if not agent.aic:
        # 如果没有AIC，则跳过证书revoke操作
        return

    try:
        # 构造 CA Server 的管理接口 URL
        ca_server_url = getattr(settings, "CA_SERVER_BASE_URL", None)
        if not ca_server_url:
            # CA Server URL 未配置，抛异常
            raise AgentException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=AgentError.REMOTE_CERT_REVOKE_FAILED,
                error_msg=f"CA Server URL is not configured",
                input_params={"agent_aic": agent.aic, "error_type": "config_error"},
            )

        revoke_url = f"{ca_server_url.rstrip('/')}/mgmt/revoke"

        # 构造请求体
        revoke_request = {"aic": agent.aic, "reason": reason}

        # 发送吊销通知给 CA Server
        response = requests.post(
            revoke_url,
            json=revoke_request,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ACPS-Registry-Server/1.0",
            },
            timeout=30,
        )

        # 记录结果，但不抛出异常以免影响主流程
        if response.status_code == 200:
            # 证书吊销通知成功
            logger.info(
                f"Successfully notified CA Server to revoke certificate for AIC: {agent.aic}"
            )
        else:
            # CA Server 返回错误，记录日志但不阻断流程
            logger.error(
                f"CA Server returned error when revoking certificate for AIC: {agent.aic}, "
                f"status_code: {response.status_code}, response: {response.text}"
            )

    except requests.exceptions.RequestException as e:
        # 网络错误，记录日志但不阻断流程
        logger.error(
            f"Network error when notifying CA Server to revoke certificate for AIC: {agent.aic}, "
            f"error: {str(e)}"
        )
    except Exception as e:
        # 其他未预期的错误，记录日志但不阻断流程
        logger.error(
            f"Unexpected error when notifying CA Server to revoke certificate for AIC: {agent.aic}, "
            f"error: {str(e)}"
        )


# TODO 还没有测试 - 保留旧的实现作为备用
def remote_cert_revoke(agent: Agent):
    """
    使用证书服务的API，远程revoke证书。
    先查询有效证书，然后逐个revoke。

    Args:
        agent: Agent对象，需要包含AIC

    Raises:
        AgentException: 如果revoke过程中发生任何错误
    """
    if not agent.aic:
        # 如果没有AIC，则跳过证书revoke操作
        return

    try:
        # 1. 获取有效证书列表
        get_certs_url = settings.CA_CERT_URL
        get_params = {"aic": agent.aic, "status": "valid"}

        # 发送GET请求查询证书
        get_response = requests.get(get_certs_url, params=get_params, timeout=30)
        get_response.raise_for_status()

        # 解析响应
        certs_data = get_response.json()

        # 假设API返回的是证书列表，每个证书有id字段
        # 具体的数据结构可能需要根据实际API调整
        if isinstance(certs_data, dict) and "data" in certs_data:
            certificates = certs_data["data"]
        elif isinstance(certs_data, list):
            certificates = certs_data
        else:
            certificates = []

        # 2. 逐个revoke证书
        revoke_errors = []
        for cert in certificates:
            try:
                cert_id = (
                    cert.get("id") or cert.get("cert_id") or cert.get("certificate_id")
                )
                if not cert_id:
                    continue

                # 构造revoke URL
                revoke_url = f"{settings.CA_CERT_URL.rstrip('/')}/{cert_id}/revoke"

                # 发送POST请求revoke证书
                revoke_response = requests.post(revoke_url, timeout=30)
                revoke_response.raise_for_status()

            except requests.exceptions.RequestException as e:
                revoke_errors.append(f"Failed to revoke cert {cert_id}: {str(e)}")
            except Exception as e:
                revoke_errors.append(
                    f"Unexpected error revoking cert {cert_id}: {str(e)}"
                )

        # 如果有revoke失败的证书，记录但不抛出异常，因为主要目标是禁用agent
        if revoke_errors:
            # 可以记录日志，但不阻断流程
            pass

    except requests.exceptions.RequestException as e:
        # 网络相关错误
        raise AgentException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            error_name=AgentError.REMOTE_CERT_REVOKE_FAILED,
            error_msg=f"Failed to communicate with certificate service: {str(e)}",
            input_params={"agent_aic": agent.aic, "error_type": "network_error"},
        )
    except Exception as e:
        # 其他未预期的错误
        raise AgentException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=AgentError.REMOTE_CERT_REVOKE_FAILED,
            error_msg=f"Unexpected error during certificate revocation: {str(e)}",
            input_params={"agent_aic": agent.aic, "error_type": "unexpected_error"},
        )


def search_agents(
    db: Session, query: str, page_size: int = 10, page_num: int = 1
) -> Tuple[List[Agent], int]:
    """使用向量搜索查找 Agent"""
    # 计算分页偏移量
    skip = (page_num - 1) * page_size

    try:
        # 获取向量搜索结果
        agent_ids = search_agents_by_vector(query, page_size)

        if not agent_ids:
            return [], 0

        # 转换为 UUID 对象
        uuid_ids = [uuid.UUID(id_str) for id_str in agent_ids]

        # 查询数据库，自动加载关联用户
        agents = (
            db.query(Agent)
            .filter(
                Agent.id.in_(uuid_ids),
                Agent.approval_status == ApprovalStatus.APPROVED,
                Agent.is_active == True,
            )
            .all()
        )

        # 按搜索结果顺序排序
        agent_map = {str(agent.id): agent for agent in agents}
        sorted_agents = [
            agent_map[agent_id] for agent_id in agent_ids if agent_id in agent_map
        ]

        return sorted_agents, len(sorted_agents)
    except Exception as e:
        # 如果 search_agents_by_vector 抛出 AgentException，直接传递
        if isinstance(e, AgentException):
            raise
        # 否则包装成新的 AgentException
        raise AgentException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=AgentError.VECTOR_SEARCH_FAILED,
            error_msg=f"Vector search failed: {str(e)}",
            input_params={"query": query},
        )


def get_recent_agents(
    db: Session, limit: int = 5, with_users: bool = False
) -> List[Agent]:
    """获取最近批准的 Agent

    Args:
        db: 数据库会话
        limit: 返回的条数限制
        with_users: 是否加载关联的用户信息
    """
    # 构建查询
    query = db.query(Agent).filter(
        Agent.approval_status == ApprovalStatus.APPROVED, Agent.is_active == True
    )

    # 如果需要加载关联用户
    if with_users:
        query = query.options(
            joinedload(Agent.created_by), joinedload(Agent.processed_by)
        )

    # 应用排序和限制
    agents = query.order_by(Agent.processed_at.desc()).limit(limit).all()

    return agents
