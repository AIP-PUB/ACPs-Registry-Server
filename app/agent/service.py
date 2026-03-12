from typing import List, Optional, Dict, Any, Tuple
import uuid
import time
import json
import requests
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from sqlalchemy.orm import Session, joinedload
from fastapi import status

from app.agent.model import Agent, ApprovalStatus
from app.agent.schema import AgentResponse, AgentDetailResponse
from app.account.schema_account import UserResponse
from app.sync.service import create_change_log
from app.agent.exception import (
    AgentException,
    AgentError,
    AtrException,
    AtrErrorCode,
)
from app.sync.service import (
    trigger_data_change_webhook,
)
from app.utils.utils import get_beijing_time, sha256
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

    if agent.acs is None:
        return

    # 确保 acs_data 是一个字典副本，避免直接修改 agent.acs 引用
    # 这样可以确保比较逻辑的正确性，并且在赋值回 agent.acs 时能触发 SQLAlchemy 的变更检测
    if isinstance(agent.acs, dict):
        acs_data = agent.acs.copy()
    else:
        # 如果不是 dict (例如是字符串)，尝试解析为 dict
        try:
            acs_data = json.loads(agent.acs)
        except json.JSONDecodeError:
            # 如果解析失败，无法更新 ACS 数据
            raise AgentException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AgentError.AGENT_INVALID_ACS,
                error_msg="Invalid ACS data format; must be a valid JSON object",
                input_params={"agent_id": str(agent.id)},
            )

    is_acs_changed = False

    # 检查并更新aic字段（小写）
    if agent.aic:
        current_aic = acs_data.get("aic")
        if current_aic != agent.aic:
            acs_data["aic"] = agent.aic
            is_acs_changed = True

    # 检查并更新active字段（布尔值）
    expected_active = agent.is_active
    current_active = acs_data.get("active")
    if current_active != expected_active:
        acs_data["active"] = expected_active
        is_acs_changed = True

    # 如果有变化，更新agent.acs
    if is_acs_changed:
        # 添加lastModifiedTime字段（北京时间带时区，ISO格式）
        current_time = get_beijing_time()
        acs_data["lastModifiedTime"] = current_time.isoformat()

        # JSONB 类型，赋值新 dict 以触发更新 (SQLAlchemy 需要检测到对象变化)
        agent.acs = acs_data

    # 如果ACS发生了变化且提供了数据库会话，则调用同步函数
    if is_acs_changed and db is not None:
        from app.sync.service import update_agent_with_changelog

        # 准备仅包含acs的agent_data，让update_agent_with_changelog处理同步相关字段
        # JSONB 类型直接传递 dict
        agent_data = {"acs": agent.acs}

        try:
            # 调用同步函数，传入agent对象而不是agent_id
            update_agent_with_changelog(db, agent, agent_data)
        except Exception as e:
            # 如果同步失败，抛出异常，由上层事务回滚
            raise e


def get_agents(
    db: Session,
    page_num: int = 1,
    page_size: int = 10,
    statuses: Optional[List[ApprovalStatus]] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    aic: Optional[str] = None,
    name_like: Optional[str] = None,
    version_like: Optional[str] = None,
    aic_like: Optional[str] = None,
    create_by_id: Optional[uuid.UUID] = None,
    process_by_id: Optional[uuid.UUID] = None,
    with_users: bool = False,
    is_active: Optional[bool] = None,
    is_deleted: Optional[bool] = None,
    is_disabled: Optional[bool] = None,
    is_ontology: Optional[bool] = None,
) -> Tuple[List[Agent], int]:
    """获取 Agent 列表，带过滤和分页

    Args:
        db: 数据库会话
        page_num: 页码，从1开始
        page_size: 每页数量
        statuses: 按审批状态过滤，支持多个状态
        name: 按名称精确匹配
        version: 按版本精确匹配
        aic: 按 AIC 精确匹配
        name_like: 按名称模糊匹配
        version_like: 按版本模糊匹配
        aic_like: 按 AIC 关键词模糊匹配
        create_by_id: 按创建者ID过滤
        process_by_id: 按处理人ID过滤
        with_users: 是否加载关联的用户信息
        is_active: Tri-state 过滤 is_active，None 表示不过滤
        is_deleted: Tri-state 过滤 is_deleted，None 表示不过滤
        is_disabled: Tri-state 过滤 is_disabled，None 表示不过滤
        is_ontology: 过滤 is_ontology，None 表示不过滤
    """
    # 基础查询
    query = db.query(Agent)

    if is_active is not None:
        query = query.filter(Agent.is_active == is_active)

    if is_deleted is not None:
        query = query.filter(Agent.is_deleted == is_deleted)

    if is_disabled is not None:
        query = query.filter(Agent.is_disabled == is_disabled)

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

    # 精确匹配
    if name:
        query = query.filter(Agent.name == name)

    if version:
        query = query.filter(Agent.version == version)

    if aic:
        query = query.filter(Agent.aic == aic)

    # 模糊匹配
    if name_like:
        query = query.filter(Agent.name.ilike(f"%{name_like}%"))

    if version_like:
        query = query.filter(Agent.version.ilike(f"%{version_like}%"))

    if aic_like:
        query = query.filter(Agent.aic.ilike(f"%{aic_like}%"))

    # 过滤 本体/实体
    if is_ontology is not None:
        query = query.filter(Agent.is_ontology == is_ontology)

    # 获取总数
    total = query.count()

    # 计算分页偏移量
    skip = (page_num - 1) * page_size

    # 应用分页和排序
    agents = query.order_by(Agent.created_at.desc()).offset(skip).limit(page_size).all()

    return agents, total


def create_agent(db: Session, user_id: uuid.UUID, agent_data: Dict[str, Any]) -> Agent:
    from app.utils.acs import validate as validate_acs

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
    # 处理 acs：API 传入的可能是 JSON 字符串，需要转换为 dict（JSONB 类型）
    if agent_data.get("acs"):
        acs_value = agent_data["acs"]
        if isinstance(acs_value, str):
            # Validate ACS
            validate_acs(acs_value)

            # 计算 hash 基于原始字符串
            agent_data["acs_hash"] = sha256(acs_value)
            # 将字符串解析为 dict 用于 JSONB 存储
            try:
                agent_data["acs"] = json.loads(acs_value)
            except json.JSONDecodeError:
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.AGENT_CREATE_FAILED,
                    error_msg="Invalid JSON format for acs field",
                    input_params={
                        "acs": acs_value[:100] if len(acs_value) > 100 else acs_value
                    },
                )
        elif isinstance(acs_value, dict):
            # 如果已经是 dict，计算 hash 需要先序列化
            acs_string = json.dumps(acs_value, ensure_ascii=False)
            # Validate ACS
            validate_acs(acs_string)
            agent_data["acs_hash"] = sha256(acs_string)

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
            from app.utils.acs import validate as validate_acs

            acs_value = agent_data["acs"]
            # 处理 acs：API 传入的可能是 JSON 字符串，需要转换为 dict（JSONB 类型）
            if isinstance(acs_value, str):
                # Validate ACS
                validate_acs(acs_value)
                # Calculate acs_hash 基于原始字符串
                new_acs_hash = sha256(acs_value)
                # 将字符串解析为 dict 用于 JSONB 存储
                try:
                    agent_data["acs"] = json.loads(acs_value)
                except json.JSONDecodeError:
                    raise AgentException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_name=AgentError.AGENT_UPDATE_FAILED,
                        error_msg="Invalid JSON format for acs field",
                        input_params={
                            "acs": (
                                acs_value[:100] if len(acs_value) > 100 else acs_value
                            )
                        },
                    )
            elif isinstance(acs_value, dict):
                # 如果已经是 dict，计算 hash 需要先序列化
                acs_string = json.dumps(acs_value, ensure_ascii=False)
                # Validate ACS
                validate_acs(acs_string)
                new_acs_hash = sha256(acs_string)
            else:
                new_acs_hash = None

            if new_acs_hash:
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
        # raise AgentException(
        #     status_code=status.HTTP_400_BAD_REQUEST,
        #     error_name=AgentError.INVALID_STATUS_TRANSITION,
        #     error_msg="Only agents in pending status can be processed",
        #     input_params={"agent_id": str(agent_id), "status": agent.approval_status},
        # )
        ...

    # Update status based on approval decision - using Beijing time
    agent.approval_status = (
        ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    )
    agent.processed_by_id = processor_id
    agent.processed_at = get_beijing_time()
    agent.process_comments = comments
    agent.updated_at = get_beijing_time()

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
            if agent.is_ontology:
                agent.aic = aic.generate_ontology_aic()
            else:
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

    # 收集需要删除的 Agent 列表
    agents_to_delete = [agent]

    # 如果是本体且已分配 AIC，则查找所有派生的实体一并删除
    if agent.is_ontology and agent.aic:
        # 查找所有 AIC 以本体 AIC 的 1~7 级（含前缀/注册商/供应商/本体序列号）为前缀的实体（排除本体自身）
        ontology_prefix = aic.get_derived_entity_like_prefix(agent.aic)
        if not ontology_prefix:
            ontology_prefix = "__invalid_aic_prefix__"
        derived_entities = (
            db.query(Agent)
            .filter(
                Agent.aic.like(f"{ontology_prefix}%"),
                Agent.id != agent.id,
                Agent.is_deleted == False,  # 只处理未删除的
            )
            .all()
        )
        agents_to_delete.extend(derived_entities)

    # 遍历处理每个 Agent 的删除逻辑
    for target_agent in agents_to_delete:
        target_agent.is_active = False
        target_agent.is_deleted = True
        target_agent.deleted_at = current_time
        target_agent.deleted_reason = reason
        target_agent.updated_at = current_time

        # 更新Agent的acs数据
        update_agent_acs_data(target_agent, db)

        # 通知 CA Server 吊销证书（使用 ATR 协议）
        notify_ca_server_revoke_cert(target_agent, reason=5)  # cessationOfOperation

        # 更新数据库
        db.add(target_agent)

    db.commit()

    # 触发数据变更通知
    # update_agent_acs_data 会自动创建 changelog，这里只需触发 webhook 通知订阅者
    try:
        trigger_data_change_webhook(db, ["acs"])
    except Exception as e:
        # 记录错误但不影响主流程
        print(f"Failed to trigger webhook for agent deletion: {str(e)}")

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

    # 收集需要禁用的 Agent 列表
    agents_to_disable = [agent]

    # 如果是本体且已分配 AIC，则查找所有派生的实体一并禁用
    if agent.is_ontology and agent.aic:
        # 查找所有 AIC 以本体 AIC 的 1~7 级为前缀的实体（排除本体自身）
        ontology_prefix = aic.get_derived_entity_like_prefix(agent.aic)
        if not ontology_prefix:
            ontology_prefix = "__invalid_aic_prefix__"
        derived_entities = (
            db.query(Agent)
            .filter(
                Agent.aic.like(f"{ontology_prefix}%"),
                Agent.id != agent.id,
                Agent.is_active == True,  # 只处理当前活跃的
                Agent.is_disabled == False,  # 且未被禁用的
            )
            .all()
        )
        agents_to_disable.extend(derived_entities)

    # 遍历处理每个 Agent 的禁用逻辑
    for target_agent in agents_to_disable:
        target_agent.is_active = False
        target_agent.is_disabled = True
        target_agent.disabled_at = current_time
        target_agent.disabled_reason = reason
        target_agent.updated_at = current_time

        # 更新Agent的acs数据
        update_agent_acs_data(target_agent, db)

        # 通知 CA Server 吊销证书（使用 ATR 协议）
        notify_ca_server_revoke_cert(target_agent, reason=5)  # cessationOfOperation

        # 更新数据库
        db.add(target_agent)

    db.commit()

    # 刷新主 agent 以返回最新状态
    db.refresh(agent)

    # 触发数据变更通知
    # update_agent_acs_data 会自动创建 changelog，这里只需触发 webhook 通知订阅者
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

    # 收集需要启用的 Agent 列表
    agents_to_enable = [agent]

    # 如果是本体且已分配 AIC，则查找所有派生的实体一并启用
    if agent.is_ontology and agent.aic:
        # 查找所有 AIC 以本体 AIC 的 1~7 级为前缀的实体（排除本体自身）
        ontology_prefix = aic.get_derived_entity_like_prefix(agent.aic)
        if not ontology_prefix:
            ontology_prefix = "__invalid_aic_prefix__"
        derived_entities = (
            db.query(Agent)
            .filter(
                Agent.aic.like(f"{ontology_prefix}%"),
                Agent.id != agent.id,
                Agent.is_disabled == True,  # 只处理当前被禁用的
            )
            .all()
        )
        agents_to_enable.extend(derived_entities)

    # 遍历处理每个 Agent 的启用逻辑
    for target_agent in agents_to_enable:
        target_agent.is_disabled = False
        target_agent.disabled_at = None
        target_agent.disabled_reason = None
        target_agent.updated_at = current_time

        # 如果Owner未删除，则激活
        if target_agent.is_deleted is False:
            target_agent.is_active = True

        # 更新Agent的acs数据
        update_agent_acs_data(target_agent, db)

        # 提示：远程证书没有激活的能力，需要重新申请新证书。

        db.add(target_agent)

    db.commit()

    # 刷新主 agent 以返回最新状态
    db.refresh(agent)

    # 触发数据变更通知
    # update_agent_acs_data 会自动创建 changelog，这里只需触发 webhook 通知订阅者
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

    # Mock 模式：跳过真实调用，直接记录日志并返回
    if settings.CA_SERVER_MOCK:
        logger.info(
            f"[Mock] Skipped CA Server revoke notification for AIC: {agent.aic} "
            f"(reason={reason})"
        )
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

        revoke_url = f"{ca_server_url.rstrip('/')}/ca/revoke-notify"

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


def register_entity(
    db: Session,
    ontology_aic: str,
    end_points: Optional[List[Dict[str, Any]]] = None,
    entity_meta: Optional[Dict[str, Any]] = None,
    entity_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    基于本体 AIC 注册新的智能体实体

    根据 ATR-Registry-Server.md 规范实现实体注册逻辑：
    1. 验证本体 AIC 存在且处于 active 状态
    2. 生成新的实体 AIC（保留本体的 1~7/9 级段，重生成第 8 级实例序列号并重算 CRC）
    3. 基于本体 ACS 和请求中的增量信息，创建实体 ACS
    4. 创建新的 Agent 记录（自动审批通过）
    5. 返回 EntityRegistrationResult

    Args:
        db: 数据库会话
        ontology_aic: 本体的 AIC（不定长点分 10 段；实例序列号为全 0）
        end_points: 实体的服务端点列表（可选）
        entity_meta: 实体的额外元数据（可选）
        entity_user_id: 绑定的终端用户 ID（可选）

    Returns:
        Dict[str, Any]: EntityRegistrationResult 格式的结果
            - ontologyAic: 本体 AIC
            - entityAic: 新分配的实体 AIC
            - endPoints: 实体的服务端点列表
            - entityMeta: 实体的额外元数据

    Raises:
        AgentException: 各种验证失败或处理错误
    """
    import json
    from app.utils.aic import generate_entity_aic_from_ontology

    # 1. 查找本体 Agent
    ontology_agent = db.query(Agent).filter(Agent.aic == ontology_aic).first()

    if not ontology_agent:
        raise AtrException(
            code=AtrErrorCode.ONTOLOGY_NOT_FOUND,
            message="Ontology AIC does not exist",
            http_status=status.HTTP_404_NOT_FOUND,
            data={"ontologyAic": ontology_aic},
        )

    # 2. 检查本体是否处于 active 状态
    if (
        not ontology_agent.is_active
        or ontology_agent.is_disabled
        or ontology_agent.is_deleted
    ):
        raise AtrException(
            code=AtrErrorCode.ONTOLOGY_INACTIVE,
            message="Ontology is inactive, disabled or deleted",
            http_status=status.HTTP_403_FORBIDDEN,
            data={
                "ontologyAic": ontology_aic,
                "isActive": ontology_agent.is_active,
                "isDisabled": ontology_agent.is_disabled,
                "isDeleted": ontology_agent.is_deleted,
            },
        )

    # 3. 检查是否为本体（is_ontology=True 才能派生实体）
    if not ontology_agent.is_ontology:
        raise AtrException(
            code=AtrErrorCode.INVALID_REQUEST,
            message="The specified AIC is not an ontology. Only ontologies can derive entities.",
            http_status=status.HTTP_400_BAD_REQUEST,
            data={
                "ontologyAic": ontology_aic,
                "isOntology": ontology_agent.is_ontology,
            },
        )

    # 4. 检查本体是否已审批通过
    if ontology_agent.approval_status != ApprovalStatus.APPROVED:
        raise AtrException(
            code=AtrErrorCode.ONTOLOGY_INACTIVE,
            message="Ontology is not approved",
            http_status=status.HTTP_403_FORBIDDEN,
            data={
                "ontologyAic": ontology_aic,
                "approvalStatus": ontology_agent.approval_status.value,
            },
        )

    # 4. 检查服务端点是否与已有实体冲突（使用 PostgreSQL JSONB 查询）
    if end_points:
        endpoint_urls = [ep.get("url") for ep in end_points if ep.get("url")]

        if endpoint_urls:
            # 查询是否有其他活跃的 Agent 的 endPoints 数组中包含相同的 URL
            # 使用 jsonb_array_elements 展开数组并检查 url 字段
            for url in endpoint_urls:
                # 使用原生 SQL 进行 JSONB 数组元素查询
                conflict_query = db.execute(
                    text(
                        """
                        SELECT aic 
                        FROM agent 
                        WHERE is_active = true 
                          AND is_deleted = false 
                          AND aic != :ontology_aic
                          AND acs IS NOT NULL
                          AND EXISTS (
                              SELECT 1 
                              FROM jsonb_array_elements(acs->'endPoints') AS ep 
                              WHERE ep->>'url' = :url
                          )
                        LIMIT 1
                    """
                    ),
                    {"ontology_aic": ontology_aic, "url": url},
                )
                conflict_result = conflict_query.fetchone()

                if conflict_result:
                    raise AtrException(
                        code=AtrErrorCode.ENDPOINT_CONFLICT,
                        message="Service endpoint URL conflicts with existing entity",
                        http_status=status.HTTP_409_CONFLICT,
                        data={
                            "conflictingUrl": url,
                            "existingAic": conflict_result[0],
                        },
                    )

    # 5. 生成实体 AIC
    entity_aic = generate_entity_aic_from_ontology(ontology_aic)
    if not entity_aic:
        raise AtrException(
            code=AtrErrorCode.GENERATE_AIC_FAILED,
            message="Failed to generate entity AIC",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            data={"ontologyAic": ontology_aic},
        )

    # 确保生成的实体 AIC 不重复
    max_attempts = 10
    for attempt in range(max_attempts):
        existing = db.query(Agent).filter(Agent.aic == entity_aic).first()
        if not existing:
            break
        entity_aic = generate_entity_aic_from_ontology(ontology_aic)
        if attempt == max_attempts - 1:
            raise AtrException(
                code=AtrErrorCode.GENERATE_AIC_FAILED,
                message="Failed to generate unique entity AIC after multiple attempts",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={"ontologyAic": ontology_aic},
            )

    # 6. 基于本体 ACS 创建实体 ACS
    current_time = get_beijing_time()
    entity_acs_data = {}

    # 从本体 ACS 继承字段（acs 现在是 JSONB 类型，直接是 dict）
    if ontology_agent.acs and isinstance(ontology_agent.acs, dict):
        ontology_acs = ontology_agent.acs
        # 继承本体的主要字段
        entity_acs_data = {
            "aic": entity_aic,
            "active": True,
            "name": ontology_acs.get("name", ontology_agent.name),
            "version": ontology_acs.get("version", ontology_agent.version),
            "provider": ontology_acs.get("provider"),
            "securitySchemes": ontology_acs.get("securitySchemes", {}),
            "capabilities": ontology_acs.get("capabilities", {}),
            "skills": ontology_acs.get("skills", []),
            "lastModifiedTime": current_time.isoformat(),
        }
    else:
        entity_acs_data = {
            "aic": entity_aic,
            "active": True,
            "name": ontology_agent.name,
            "version": ontology_agent.version,
            "lastModifiedTime": current_time.isoformat(),
        }

    # 构造实体名称以满足 name+version 唯一约束：使用实体 AIC 的第 8 级（实例序列号）作为后缀
    instance_serial = aic.get_instance_serial(entity_aic) if entity_aic else None
    suffix = instance_serial[-8:] if instance_serial else None
    base_name = entity_acs_data.get("name") or ontology_agent.name or "Entity"
    if suffix:
        # 先截断主体到 255-9 个字符，再拼接 8 位后缀，中间用-连接，确保长度受限且保持唯一
        truncated_base = base_name[:246]
        derived_name = f"{truncated_base}-{suffix}"
    else:
        derived_name = base_name[:255]
    entity_acs_data["name"] = derived_name

    # 使用请求中提供的 endPoints（覆盖本体的端点）
    if end_points:
        entity_acs_data["endPoints"] = end_points
    elif ontology_agent.acs and isinstance(ontology_agent.acs, dict):
        if "endPoints" in ontology_agent.acs:
            entity_acs_data["endPoints"] = ontology_agent.acs["endPoints"]

    # 添加 entityMeta
    if entity_meta:
        entity_acs_data["entityMeta"] = entity_meta

    if entity_user_id:
        entity_acs_data["entityUserId"] = entity_user_id

    # acs_hash 需要基于 JSON 字符串计算
    entity_acs_str = json.dumps(entity_acs_data, ensure_ascii=False)

    # 7. 从 ACS 中提取必要字段创建 Agent 记录
    agent_name = entity_acs_data.get("name", f"Entity of {ontology_agent.name}")
    agent_version = entity_acs_data.get("version", ontology_agent.version)
    agent_description = ontology_agent.description

    # 8. 创建新的 Agent 记录（acs 使用 dict，JSONB 类型）
    new_agent = Agent(
        aic=entity_aic,
        name=agent_name,
        version=agent_version,
        description=agent_description,
        logo_url=ontology_agent.logo_url,
        acs=entity_acs_data,  # JSONB 类型，直接传 dict
        acs_hash=sha256(entity_acs_str),
        acs_version=1,
        is_active=True,
        is_deleted=False,
        is_disabled=False,
        created_by_id=ontology_agent.created_by_id,  # 继承本体的创建者
        created_at=current_time,
        updated_at=current_time,
        approval_status=ApprovalStatus.APPROVED,  # 实体自动审批通过
        submitted_at=current_time,
        processed_at=current_time,
        processed_by_id=ontology_agent.created_by_id,  # 自动审批
        process_comments="Auto-approved via ATR entity registration",
    )

    try:
        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)

        # 9. 创建同步日志
        try:
            create_change_log(db, new_agent.aic, new_agent.acs, new_agent.acs_hash)
        except Exception as e:
            logger.warning(f"Failed to create change log for entity {entity_aic}: {e}")

        # # 10. 尝试索引到向量数据库
        # try:
        #     index_agent(new_agent)
        # except Exception as e:
        #     logger.warning(
        #         f"Failed to index entity {entity_aic} to vector database: {e}"
        #     )

        # logger.info(
        #     f"Successfully registered entity {entity_aic} based on ontology {ontology_aic}"
        # )

        # 11. 构造并返回 EntityRegistrationResult
        result = {
            "ontologyAic": ontology_aic,
            "entityAic": entity_aic,
        }
        if end_points:
            result["endPoints"] = end_points
        if entity_meta:
            result["entityMeta"] = entity_meta
        if entity_user_id:
            result["entityUserId"] = entity_user_id

        return result

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during entity registration: {e}")
        raise AtrException(
            code=AtrErrorCode.DATABASE_ERROR,
            message="Database error during entity registration",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            data={"ontologyAic": ontology_aic, "error": str(e)},
        )


def generate_jsonc_sample_from_schema(
    schema, root_schema=None, indent=0
) -> Tuple[str, str]:
    if root_schema is None:
        root_schema = schema

    spaces = " " * indent
    description = schema.get("description", "")

    # Resolve $ref
    if "$ref" in schema:
        ref_path = schema["$ref"]
        if ref_path.startswith("#/"):
            parts = ref_path.split("/")
            current = root_schema
            for part in parts[1:]:
                current = current.get(part, {})

            resolved_val, resolved_desc = generate_jsonc_sample_from_schema(
                current, root_schema, indent
            )
            final_desc = description if description else resolved_desc
            return resolved_val, final_desc

    # Handle anyOf, allOf, oneOf (simplified - take first)
    if "anyOf" in schema and schema["anyOf"]:
        return generate_jsonc_sample_from_schema(
            schema["anyOf"][0], root_schema, indent
        )
    if "oneOf" in schema and schema["oneOf"]:
        return generate_jsonc_sample_from_schema(
            schema["oneOf"][0], root_schema, indent
        )
    if "allOf" in schema and schema["allOf"]:
        return generate_jsonc_sample_from_schema(
            schema["allOf"][0], root_schema, indent
        )

    type_ = schema.get("type")

    # Try to get example value
    example_val = None
    has_example = False
    if "examples" in schema and schema["examples"]:
        example_val = schema["examples"][0]
        has_example = True

    if type_ == "object":
        properties = schema.get("properties", {})
        if not properties:
            if has_example:
                val_str = json.dumps(example_val, ensure_ascii=False, indent=2).replace(
                    "\n", "\n" + spaces
                )
                return val_str, description
            return "{}", description

        lines = []
        lines.append("{")

        prop_items = list(properties.items())
        for i, (prop_name, prop_schema) in enumerate(prop_items):
            val_str, child_desc = generate_jsonc_sample_from_schema(
                prop_schema, root_schema, indent + 2
            )

            comma = "," if i < len(prop_items) - 1 else ""
            line_prefix = f'{spaces}  "{prop_name}": '

            child_desc = child_desc.replace("\n", " ")

            if "\n" in val_str:
                if child_desc:
                    lines.append(f"{spaces}  // {child_desc}")
                lines.append(f"{line_prefix}{val_str}{comma}")
            else:
                line = f"{line_prefix}{val_str}{comma}"
                if child_desc:
                    line += f" // {child_desc}"
                lines.append(line)

        lines.append(f"{spaces}}}")
        return "\n".join(lines), description

    elif type_ == "array":
        items_schema = schema.get("items", {})
        item_type = items_schema.get("type")

        if has_example and item_type in ["string", "number", "integer", "boolean"]:
            val_str = json.dumps(example_val, ensure_ascii=False, indent=2).replace(
                "\n", "\n" + spaces
            )
            return val_str, description

        val_str, item_desc = generate_jsonc_sample_from_schema(
            items_schema, root_schema, indent + 2
        )

        lines = []
        lines.append("[")
        if "\n" in val_str:
            lines.append(f"{spaces}  {val_str}")
        else:
            lines.append(f"{spaces}  {val_str}")

        lines.append(f"{spaces}]")
        return "\n".join(lines), description

    else:
        val = "null"
        if has_example:
            val = json.dumps(example_val, ensure_ascii=False)
        else:
            if type_ == "string":
                val = '"string"'
            elif type_ == "boolean":
                val = "true"
            elif type_ == "integer":
                val = "0"
            elif type_ == "number":
                val = "0.0"

        return val, description
