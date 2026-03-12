from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
import json
import uuid
import math
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text, func, or_
from fastapi import status

from app.sync.model import ChangeLog, Snapshot, WebHook
from app.sync.schema import Envelope, ChangeLogResponse, SnapshotInfo
from app.sync.exception import SyncException, SyncError
from app.agent.model import Agent
from app.utils.utils import get_beijing_time, sha256
from app.core.config import settings
from app.core.db_session import SessionLocal


def generate_next_seq(db: Session) -> int:
    """生成下一个全局序列号"""
    try:
        result = db.execute(text("SELECT nextval('global_seq')"))
        seq = result.scalar()
        return seq
    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.GLOBAL_SEQ_GENERATE_FAILED,
            error_msg=f"Failed to generate global sequence: {str(e)}",
            input_params={},
        )


def create_change_log(
    db: Session,
    data_type: str,
    object_id: str,
    version: int,
    payload: Optional[Any] = None,
    op: str = "upsert",  # 新增操作类型参数，默认为upsert
    seq: Optional[int] = None,
) -> ChangeLog:
    """创建变更日志记录"""
    try:
        # 如果没有提供seq，则生成新的
        if seq is None:
            seq = generate_next_seq(db)

        change_log = ChangeLog(
            seq=seq,
            ts=get_beijing_time(),
            type=data_type,
            op=op,  # 添加操作类型
            id=object_id,
            version=version,
            payload=payload,
        )

        db.add(change_log)
        # 注意：这里不提交事务，让调用方控制事务
        return change_log

    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGELOG_CREATE_FAILED,
            error_msg=f"Failed to create change log entry: {str(e)}",
            input_params={
                "object_id": object_id,
                "version": version,
                "type": data_type,
            },
        )


def update_agent_with_changelog(
    db: Session, agent: Agent, agent_data: Dict[str, Any]
) -> Agent:
    """
    更新Agent并在acs数据变化时创建ChangeLog记录
    这个函数在一个事务中完成以下操作：
    1. 检查acs是否变化
    2. 如果变化，生成新的seq
    3. 更新Agent的acs_version和acs_last_seq
    4. 创建ChangeLog记录

    注意：此函数不修改ACS的内容，ACS内容的更新由update_agent_acs_data负责

    Args:
        db: 数据库会话
        agent: Agent对象实例（不是agent_id）
        agent_data: 要更新的数据
    """
    try:
        # 检查是否有acs数据变化
        acs_changed = False
        new_acs_hash = None

        if "acs" in agent_data:
            new_acs = agent_data["acs"]
            if new_acs:
                # acs 现在是 JSONB 类型（dict），需要序列化为字符串来计算 hash
                if isinstance(new_acs, dict):
                    new_acs_hash = sha256(json.dumps(new_acs, ensure_ascii=False))
                elif isinstance(new_acs, str):
                    new_acs_hash = sha256(new_acs)
                else:
                    new_acs_hash = None
            else:
                new_acs_hash = None

            # 比较acs_hash是否不同
            if new_acs_hash != agent.acs_hash:
                acs_changed = True

        if acs_changed:
            # 生成新的seq值
            new_seq = generate_next_seq(db)

            # 更新Agent的acs相关字段（但不修改acs内容本身）
            agent.acs_hash = new_acs_hash
            agent.acs_version = (agent.acs_version or 0) + 1
            agent.acs_last_seq = new_seq

            # 创建ChangeLog记录
            if agent.aic:  # 只有有AIC的Agent才记录ChangeLog
                create_change_log(
                    db=db,
                    data_type="acs",
                    object_id=agent.aic,
                    version=agent.acs_version,
                    payload=agent_data["acs"],  # 使用传入的acs数据
                    op="upsert",  # 更新操作默认为upsert
                    seq=new_seq,
                )

        # 更新其他字段（除了acs相关的同步字段）
        for key, value in agent_data.items():
            if key not in [
                "acs",
                "acs_hash",
                "acs_version",
                "acs_last_seq",
            ] and hasattr(agent, key):
                setattr(agent, key, value)

        # 更新时间戳
        agent.updated_at = get_beijing_time()

        # 注意：这里不调用db.add(agent)，让调用方控制
        # 也不提交事务，让调用方控制事务

        return agent

    except Exception as e:
        if isinstance(e, SyncException):
            raise
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGELOG_CREATE_FAILED,
            error_msg=f"Failed to update agent with changelog: {str(e)}",
            input_params={"agent_id": str(agent.id), "agent_data": agent_data},
        )


def get_changes(
    db: Session,
    seq: Optional[int] = None,
    limit: int = 1000,
    types: Optional[List[str]] = None,
) -> Tuple[List[Envelope], int]:
    """
    获取增量变更数据
    返回: (变更列表, 下一个seq号)
    """
    try:
        # 检查保留窗口
        if seq is not None:
            # 获取最老的seq号
            oldest_seq_result = db.query(func.min(ChangeLog.seq)).scalar()
            if oldest_seq_result and seq < oldest_seq_result:
                # 超出保留窗口
                raise SyncException(
                    status_code=status.HTTP_410_GONE,
                    error_name=SyncError.RETENTION_WINDOW_EXCEEDED,
                    error_msg=f"Requested seq {seq} is too old. Oldest available seq is {oldest_seq_result}. Please perform a snapshot sync.",
                    input_params={
                        "requested_seq": seq,
                        "oldest_seq": oldest_seq_result,
                    },
                )

        query = db.query(ChangeLog)

        # 过滤seq
        if seq is not None:
            query = query.filter(ChangeLog.seq > seq)

        # 过滤类型
        if types:
            query = query.filter(ChangeLog.type.in_(types))

        # 按seq排序并限制数量
        changes = query.order_by(ChangeLog.seq).limit(limit).all()

        # 转换为Envelope格式
        envelopes = []
        next_seq = seq or 0

        for change in changes:
            try:
                # 解析payload
                payload_data = None
                if change.payload is not None:
                    if isinstance(change.payload, str):
                        payload_data = json.loads(change.payload)
                    else:
                        payload_data = change.payload

                envelope = Envelope(
                    seq=change.seq,
                    ts=change.ts,
                    op=change.op,  # 添加操作类型
                    type=change.type,
                    id=change.id,
                    version=change.version,
                    payload=payload_data,
                )
                envelopes.append(envelope)
                next_seq = change.seq

            except json.JSONDecodeError:
                # 如果JSON解析失败，跳过这条记录
                continue

        return envelopes, next_seq

    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to query changes: {str(e)}",
            input_params={"seq": seq, "limit": limit, "types": types},
        )


def get_changelog_list(
    db: Session,
    page_num: int = 1,
    page_size: int = 10,
    object_id: Optional[str] = None,
    data_type: Optional[str] = None,
) -> Tuple[List[ChangeLog], int]:
    """获取变更日志列表"""
    try:
        query = db.query(ChangeLog)

        # 应用过滤条件
        if object_id:
            query = query.filter(ChangeLog.id == object_id)
        if data_type:
            query = query.filter(ChangeLog.type == data_type)

        # 获取总数
        total = query.count()

        # 计算分页偏移量
        skip = (page_num - 1) * page_size

        # 应用分页和排序
        change_logs = (
            query.order_by(ChangeLog.seq.desc()).offset(skip).limit(page_size).all()
        )

        return change_logs, total

    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to query change logs: {str(e)}",
            input_params={
                "page_num": page_num,
                "page_size": page_size,
                "object_id": object_id,
                "data_type": data_type,
            },
        )


def get_retention_oldest_seq(db: Session, window_hours: int, max_records: int) -> int:
    """
    获取保留窗口内最老的seq号
    基于时间窗口和最大记录数两个条件
    """
    try:
        current_time = get_beijing_time()
        cutoff_time = current_time - timedelta(hours=window_hours)

        # 基于时间窗口的最老seq：在cutoff_time之后的最小seq
        time_based_seq = (
            db.query(func.min(ChangeLog.seq))
            .filter(ChangeLog.ts >= cutoff_time)
            .scalar()
        )

        # 基于最大记录数的最老seq：最新max_records条记录中的最小seq
        record_based_seq = (
            db.query(ChangeLog.seq)
            .order_by(ChangeLog.seq.desc())
            .offset(max_records - 1)
            .limit(1)
            .scalar()
        )

        # 选择合适的保留策略
        oldest_seq = 1  # 默认最小值

        if time_based_seq and record_based_seq:
            # 两个条件都有值，选择更保守的（保留更多数据）
            oldest_seq = max(time_based_seq, record_based_seq)
        elif time_based_seq:
            # 只有时间窗口条件
            oldest_seq = time_based_seq
        elif record_based_seq:
            # 只有记录数条件
            oldest_seq = record_based_seq
        else:
            # 都没有，查询最小seq作为保守值
            min_seq = db.query(func.min(ChangeLog.seq)).scalar()
            oldest_seq = min_seq if min_seq else 1

        return oldest_seq

    except SQLAlchemyError:
        # 如果查询失败，返回1作为保守值
        return 1


def cleanup_old_changelog_entries(
    db: Session, window_hours: int, max_records: int
) -> int:
    """
    清理超出保留窗口的旧ChangeLog条目

    Args:
        db: 数据库会话
        window_hours: 保留窗口时长（小时）
        max_records: 保留的最大记录数

    Returns:
        清理的记录数量
    """
    try:
        current_time = get_beijing_time()
        cutoff_time = current_time - timedelta(hours=window_hours)

        # 基于时间窗口删除旧记录
        time_based_delete = (
            db.query(ChangeLog)
            .filter(ChangeLog.ts < cutoff_time)
            .delete(synchronize_session=False)
        )

        # 基于最大记录数删除多余记录
        total_count = db.query(ChangeLog).count()
        record_based_delete = 0

        if total_count > max_records:
            # 获取需要保留的最小seq（最新的max_records条记录的最小seq）
            keep_seq_threshold = (
                db.query(ChangeLog.seq)
                .order_by(ChangeLog.seq.desc())
                .offset(max_records - 1)
                .limit(1)
                .scalar()
            )

            if keep_seq_threshold:
                record_based_delete = (
                    db.query(ChangeLog)
                    .filter(ChangeLog.seq < keep_seq_threshold)
                    .delete(synchronize_session=False)
                )

        total_deleted = time_based_delete + record_based_delete
        db.commit()

        # trigger_webhook_04
        if total_deleted > 0:
            trigger_retention_cleanup_webhook(
                db, total_deleted, window_hours, max_records
            )

        return total_deleted

    except SQLAlchemyError as e:
        db.rollback()
        return 0


def get_current_max_seq(db: Session) -> int:
    """获取当前最大的seq号"""
    try:
        result = db.query(func.max(ChangeLog.seq)).scalar()
        return result or 0
    except SQLAlchemyError as e:
        return 0


def create_changelog_response(change_log: ChangeLog) -> ChangeLogResponse:
    """将ChangeLog ORM对象转换为响应模型"""
    return ChangeLogResponse.model_validate(change_log)


# Snapshot相关的服务函数


def generate_snapshot_id() -> str:
    """生成快照ID"""
    return f"snap_{uuid.uuid4().hex[:12]}"


def calculate_expire_time(
    access_timeout_hours: Optional[int] = None, max_lifetime_hours: Optional[int] = None
) -> datetime:
    """计算快照过期时间，取访问超时和最大生存时间的较小值"""
    if access_timeout_hours is None:
        access_timeout_hours = settings.DSP_SNAPSHOT_ACCESS_TIMEOUT_HOURS
    if max_lifetime_hours is None:
        max_lifetime_hours = settings.DSP_SNAPSHOT_MAX_LIFETIME_HOURS

    now = get_beijing_time()
    access_expire = now + timedelta(hours=access_timeout_hours)
    max_expire = now + timedelta(hours=max_lifetime_hours)
    return min(access_expire, max_expire)


def create_snapshot(
    db: Session,
    types: List[str],
    limit: int = 10000,
    from_seq: Optional[int] = None,
) -> Tuple[Snapshot, List[Envelope]]:
    """
    创建快照并返回第一个chunk的数据

    Args:
        db: 数据库会话
        types: 数据类型列表
        limit: 每个chunk的最大对象数量
        from_seq: 增量快照的起始序列号，None表示全量快照

    Returns:
        (Snapshot对象, 第一个chunk的数据)
    """
    try:
        # 生成快照ID
        snapshot_id = generate_snapshot_id()

        # 获取当前最大seq作为快照的切点
        current_seq = get_current_max_seq(db)

        # 创建物化表名
        table_name = f"snapshot_{snapshot_id.replace('snap_', '')}"

        # 构建查询，获取所有符合条件的Agent数据
        query_conditions = []
        params = {}

        # 过滤数据类型（目前只支持acs）
        if "acs" in types:
            query_conditions.append("a.acs IS NOT NULL AND a.aic IS NOT NULL")

        # 增量快照过滤条件
        if from_seq is not None:
            query_conditions.append("a.acs_last_seq > :from_seq")
            params["from_seq"] = from_seq

        # 只获取活跃且未删除的Agent
        query_conditions.append("a.is_active = true AND a.is_deleted = false")

        where_clause = " AND ".join(query_conditions) if query_conditions else "1=1"

        # 创建物化快照表的SQL（使用持久化表而不是临时表）
        create_table_sql = f"""
        CREATE TABLE {table_name} AS
        SELECT 
            COALESCE(a.acs_last_seq, 0) as seq,
            a.updated_at as ts,
            'upsert' as op,
            'acs' as type,
            a.aic as id,
            COALESCE(a.acs_version, 1) as version,
            a.acs as payload
        FROM agent a
        WHERE {where_clause}
            AND a.acs_last_seq <= :current_seq
        ORDER BY COALESCE(a.acs_last_seq, 0)
        """

        params["current_seq"] = current_seq

        # 执行创建物化表
        db.execute(text(create_table_sql), params)

        # 获取总对象数量
        count_result = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        object_count = count_result or 0

        # 计算总chunk数量
        chunk_total = max(1, math.ceil(object_count / limit))

        # 获取第一个chunk的数据
        first_chunk_sql = f"""
        SELECT seq, ts, op, type, id, version, payload
        FROM {table_name}
        ORDER BY seq
        LIMIT :limit
        """

        result = db.execute(text(first_chunk_sql), {"limit": limit})
        rows = result.fetchall()

        # 转换为Envelope格式
        envelopes = []
        for row in rows:
            try:
                # 解析payload
                payload_data = None
                if row.payload is not None:
                    if isinstance(row.payload, str):
                        payload_data = json.loads(row.payload)
                    else:
                        payload_data = row.payload

                envelope = Envelope(
                    seq=row.seq,
                    ts=row.ts,
                    op=row.op,  # 添加操作类型
                    type=row.type,
                    id=row.id,
                    version=row.version,
                    payload=payload_data,
                )
                envelopes.append(envelope)
            except json.JSONDecodeError:
                # 跳过无效的JSON数据
                continue

        # 创建Snapshot记录
        snapshot = Snapshot(
            id=snapshot_id,
            types=",".join(types),
            seq=current_seq,
            chunk_total=chunk_total,
            object_count=object_count,
            from_seq=from_seq,
            is_deleted=False,
            created_at=get_beijing_time(),
            last_access_at=get_beijing_time(),
            expire_at=calculate_expire_time(),
        )

        db.add(snapshot)
        db.commit()

        return snapshot, envelopes

    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_CREATE_FAILED,
            error_msg=f"Failed to create snapshot: {str(e)}",
            input_params={
                "types": types,
                "limit": limit,
                "from_seq": from_seq,
            },
        )


def get_snapshot_chunk(
    db: Session, snapshot_id: str, chunk_index: int, limit: int = 10000
) -> Tuple[Snapshot, List[Envelope]]:
    """
    获取快照的指定chunk数据

    Args:
        db: 数据库会话
        snapshot_id: 快照ID
        chunk_index: chunk索引（从0开始）
        limit: 每个chunk的最大对象数量

    Returns:
        (Snapshot对象, chunk数据)
    """
    try:
        # 获取快照信息
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.id == snapshot_id, Snapshot.is_deleted == False)
            .first()
        )

        if not snapshot:
            raise SyncException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_name=SyncError.SNAPSHOT_NOT_FOUND,
                error_msg=f"Snapshot {snapshot_id} not found",
                input_params={"snapshot_id": snapshot_id},
            )

        # 检查是否过期
        if get_beijing_time() > snapshot.expire_at:
            raise SyncException(
                status_code=status.HTTP_410_GONE,
                error_name=SyncError.SNAPSHOT_EXPIRED,
                error_msg=f"Snapshot {snapshot_id} has expired",
                input_params={"snapshot_id": snapshot_id},
            )

        # 检查chunk索引是否有效
        if chunk_index < 0 or chunk_index >= snapshot.chunk_total:
            raise SyncException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=SyncError.INVALID_CHUNK_INDEX,
                error_msg=f"Invalid chunk index {chunk_index}. Must be between 0 and {snapshot.chunk_total - 1}",
                input_params={
                    "snapshot_id": snapshot_id,
                    "chunk_index": chunk_index,
                    "chunk_total": snapshot.chunk_total,
                },
            )

        # 更新最后访问时间
        snapshot.last_access_at = get_beijing_time()
        db.add(snapshot)

        # 构建物化表名
        table_name = f"snapshot_{snapshot_id.replace('snap_', '')}"

        # 计算分页参数
        offset = chunk_index * limit

        # 获取chunk数据
        chunk_sql = f"""
        SELECT seq, ts, op, type, id, version, payload
        FROM {table_name}
        ORDER BY seq
        LIMIT :limit OFFSET :offset
        """

        result = db.execute(text(chunk_sql), {"limit": limit, "offset": offset})
        rows = result.fetchall()

        # 转换为Envelope格式
        envelopes = []
        for row in rows:
            try:
                # 解析payload
                payload_data = None
                if row.payload is not None:
                    if isinstance(row.payload, str):
                        payload_data = json.loads(row.payload)
                    else:
                        payload_data = row.payload

                envelope = Envelope(
                    seq=row.seq,
                    ts=row.ts,
                    op=row.op,  # 添加操作类型
                    type=row.type,
                    id=row.id,
                    version=row.version,
                    payload=payload_data,
                )
                envelopes.append(envelope)
            except json.JSONDecodeError:
                # 跳过无效的JSON数据
                continue

        db.commit()
        return snapshot, envelopes

    except SyncException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_DATA_QUERY_FAILED,
            error_msg=f"Failed to get snapshot chunk: {str(e)}",
            input_params={
                "snapshot_id": snapshot_id,
                "chunk_index": chunk_index,
                "limit": limit,
            },
        )


def delete_snapshot(db: Session, snapshot_id: str) -> bool:
    """
    删除快照及其物化表

    Args:
        db: 数据库会话
        snapshot_id: 快照ID

    Returns:
        是否成功删除
    """
    try:
        # 获取快照信息
        snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()

        if not snapshot:
            # 快照不存在时仍然返回成功，符合幂等性要求
            return True

        # 删除物化表（如果存在）
        table_name = f"snapshot_{snapshot_id.replace('snap_', '')}"
        try:
            db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        except SQLAlchemyError:
            # 忽略表删除错误，可能表已经不存在
            pass

        # 标记快照为已删除
        snapshot.is_deleted = True
        db.add(snapshot)
        db.commit()

        return True

    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_TABLE_DROP_FAILED,
            error_msg=f"Failed to delete snapshot: {str(e)}",
            input_params={"snapshot_id": snapshot_id},
        )


def cleanup_expired_snapshots(db: Session) -> int:
    """
    清理过期的快照

    Args:
        db: 数据库会话

    Returns:
        清理的快照数量
    """
    try:
        current_time = get_beijing_time()

        # 查找过期的快照
        expired_snapshots = (
            db.query(Snapshot)
            .filter(Snapshot.expire_at < current_time, Snapshot.is_deleted == False)
            .all()
        )

        cleaned_count = 0

        for snapshot in expired_snapshots:
            try:
                # 删除物化表
                table_name = f"snapshot_{snapshot.id.replace('snap_', '')}"
                db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

                # 标记为已删除
                snapshot.is_deleted = True
                db.add(snapshot)
                cleaned_count += 1

            except SQLAlchemyError:
                # 继续处理其他快照
                continue

        if cleaned_count > 0:
            db.commit()

        return cleaned_count

    except SQLAlchemyError as e:
        db.rollback()
        return 0


def get_snapshot_info(db: Session, snapshot_id: str) -> SnapshotInfo:
    """
    获取快照信息

    Args:
        db: 数据库会话
        snapshot_id: 快照ID

    Returns:
        快照信息
    """
    try:
        snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()

        if not snapshot:
            raise SyncException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_name=SyncError.SNAPSHOT_NOT_FOUND,
                error_msg=f"Snapshot {snapshot_id} not found",
                input_params={"snapshot_id": snapshot_id},
            )

        return SnapshotInfo.model_validate(snapshot)

    except SyncException:
        raise
    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_DATA_QUERY_FAILED,
            error_msg=f"Failed to get snapshot info: {str(e)}",
            input_params={"snapshot_id": snapshot_id},
        )


# WebHook相关的服务函数

import hashlib
import hmac
import time
import requests
from typing import List, Union
from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Lock, Timer

logger = logging.getLogger(__name__)


_inflight_sends_lock: Lock = Lock()
_inflight_sends = set()  # Set[tuple[str, str]] => (webhook_id, event)

_data_change_batch_lock: Lock = Lock()
_data_change_batch_state = {
    "types": set(),  # set[str]
    "max_seq": None,  # Optional[int]
    "timer": None,  # Optional[Timer]
}


def _mark_inflight(webhook_id: str, event: str) -> bool:
    """把一个webhook-event标记为正在进行中；如果已经在进行中，则返回 False"""
    with _inflight_sends_lock:
        key = (webhook_id, event)
        if key in _inflight_sends:
            return False
        _inflight_sends.add(key)
        return True


def _clear_inflight(webhook_id: str, event: str) -> None:
    """Clear the in-flight mark for a webhook-event pair."""
    with _inflight_sends_lock:
        _inflight_sends.discard((webhook_id, event))


def generate_webhook_id() -> str:
    """生成WebHook ID"""
    return f"wh_{uuid.uuid4().hex[:12]}"


def create_webhook(
    db: Session,
    url: str,
    secret: str,
    types: List[str],
    events: List[str],
    description: Optional[str] = None,
) -> WebHook:
    """
    创建WebHook

    Args:
        db: 数据库会话
        url: 回调URL
        secret: 签名密钥
        types: 关注的数据类型列表
        events: 关注的事件类型列表
        description: WebHook描述

    Returns:
        创建的WebHook对象
    """
    try:
        webhook_id = generate_webhook_id()

        webhook = WebHook(
            id=webhook_id,
            url=url,
            secret=secret,
            types=",".join(types),
            events=",".join(events),
            description=description,
            status="active",
            failure_count=0,
            created_at=get_beijing_time(),
            updated_at=get_beijing_time(),
        )

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        return webhook

    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_CREATE_FAILED,
            error_msg=f"Failed to create webhook: {str(e)}",
            input_params={
                "url": url,
                "types": types,
                "events": events,
            },
        )


def get_webhook(db: Session, webhook_id: str) -> WebHook:
    """
    获取WebHook信息

    Args:
        db: 数据库会话
        webhook_id: WebHook ID

    Returns:
        WebHook对象
    """
    try:
        webhook = db.query(WebHook).filter(WebHook.id == webhook_id).first()

        if not webhook:
            raise SyncException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_name=SyncError.WEBHOOK_NOT_FOUND,
                error_msg=f"WebHook {webhook_id} not found",
                input_params={"webhook_id": webhook_id},
            )

        return webhook

    except SyncException:
        raise
    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_QUERY_FAILED,
            error_msg=f"Failed to get webhook: {str(e)}",
            input_params={"webhook_id": webhook_id},
        )


def update_webhook(
    db: Session,
    webhook_id: str,
    url: Optional[str] = None,
    secret: Optional[str] = None,
    types: Optional[List[str]] = None,
    events: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> WebHook:
    """
    更新WebHook

    Args:
        db: 数据库会话
        webhook_id: WebHook ID
        url: 新的回调URL
        secret: 新的签名密钥
        types: 新的数据类型列表
        events: 新的事件类型列表
        description: 新的描述

    Returns:
        更新后的WebHook对象
    """
    try:
        webhook = get_webhook(db, webhook_id)

        if url is not None:
            webhook.url = url
        if secret is not None:
            webhook.secret = secret
        if types is not None:
            webhook.types = ",".join(types)
        if events is not None:
            webhook.events = ",".join(events)
        if description is not None:
            webhook.description = description

        webhook.updated_at = get_beijing_time()

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        return webhook

    except SyncException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_UPDATE_FAILED,
            error_msg=f"Failed to update webhook: {str(e)}",
            input_params={"webhook_id": webhook_id},
        )


def delete_webhook(db: Session, webhook_id: str) -> bool:
    """
    删除WebHook

    Args:
        db: 数据库会话
        webhook_id: WebHook ID

    Returns:
        是否删除成功
    """
    try:
        webhook = get_webhook(db, webhook_id)
        db.delete(webhook)
        db.commit()
        return True

    except SyncException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_DELETE_FAILED,
            error_msg=f"Failed to delete webhook: {str(e)}",
            input_params={"webhook_id": webhook_id},
        )


def reactivate_webhook(db: Session, webhook_id: str) -> WebHook:
    """
    重新激活WebHook，重置失败状态

    Args:
        db: 数据库会话
        webhook_id: WebHook ID

    Returns:
        重新激活的WebHook对象
    """
    try:
        webhook = get_webhook(db, webhook_id)

        webhook.status = "active"
        webhook.failure_count = 0
        webhook.next_retry_at = None
        webhook.last_failure_reason = None
        webhook.updated_at = get_beijing_time()

        db.add(webhook)
        db.commit()
        db.refresh(webhook)

        return webhook

    except SyncException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_REACTIVATE_FAILED,
            error_msg=f"Failed to reactivate webhook: {str(e)}",
            input_params={"webhook_id": webhook_id},
        )


def get_webhook_list(
    db: Session,
    page_num: int = 1,
    page_size: int = 10,
    status_filter: Optional[str] = None,
) -> Tuple[List[WebHook], int]:
    """
    获取WebHook列表

    Args:
        db: 数据库会话
        page_num: 页码
        page_size: 每页数量
        status_filter: 状态过滤

    Returns:
        (WebHook列表, 总数)
    """
    try:
        query = db.query(WebHook)

        if status_filter:
            query = query.filter(WebHook.status == status_filter)

        # 获取总数
        total = query.count()

        # 计算分页偏移量
        skip = (page_num - 1) * page_size

        # 应用分页和排序
        webhooks = (
            query.order_by(WebHook.created_at.desc())
            .offset(skip)
            .limit(page_size)
            .all()
        )

        return webhooks, total

    except SQLAlchemyError as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_QUERY_FAILED,
            error_msg=f"Failed to list webhooks: {str(e)}",
            input_params={
                "page_num": page_num,
                "page_size": page_size,
                "status_filter": status_filter,
            },
        )


def generate_webhook_signature(secret: str, timestamp: int, payload: str) -> str:
    """
    生成WebHook签名

    Args:
        secret: 签名密钥
        timestamp: 时间戳
        payload: 负载数据

    Returns:
        HMAC-SHA256签名
    """
    message = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"


def send_webhook_notification(
    webhook: WebHook,
    event: str,
    event_data: Dict[str, Any],
    timeout: int = 30,
    max_retries: int = 3,
) -> bool:
    """
    发送WebHook通知

    Args:
        webhook: WebHook对象
        event: 事件类型
        event_data: 事件数据
        timeout: 请求超时时间（秒）
        max_retries: 最大重试次数

    Returns:
        是否发送成功
    """
    try:
        current_time = get_beijing_time()
        timestamp = int(current_time.timestamp())

        # 构建通知载荷
        notification_payload = {
            "webhook_id": webhook.id,
            "event": event,
            "timestamp": current_time.isoformat(),
            "data": event_data,
        }

        payload_json = json.dumps(notification_payload, ensure_ascii=False)

        # 生成签名
        signature = generate_webhook_signature(webhook.secret, timestamp, payload_json)

        # 构建请求头
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-ID": webhook.id,
            "X-Webhook-Signature": signature,
            "X-Webhook-Timestamp": str(timestamp),
            "User-Agent": "ACPS-DSP-WebHook/1.0",
        }

        # 如果该webhook-event已在发送中，则跳过本次发送
        if not _mark_inflight(webhook.id, event):
            logger.info(f"Skip duplicate in-flight webhook send: {webhook.id} {event}")
            return True

        try:
            # 发送请求
            response = requests.post(
                webhook.url,
                json=notification_payload,
                headers=headers,
                timeout=timeout,
            )
        finally:
            _clear_inflight(webhook.id, event)

        # 检查响应状态
        if 200 <= response.status_code < 300:
            return True
        else:
            logger.warning(
                f"WebHook {webhook.id} returned non-2xx status: {response.status_code}"
            )
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send webhook notification: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending webhook: {str(e)}")
        return False


def update_webhook_status(
    db: Session,
    webhook_id: str,
    success: bool,
    failure_reason: Optional[str] = None,
) -> None:
    """
    更新WebHook状态

    Args:
        db: 数据库会话
        webhook_id: WebHook ID
        success: 是否成功
        failure_reason: 失败原因
    """
    try:
        webhook = db.query(WebHook).filter(WebHook.id == webhook_id).first()

        if not webhook:
            return

        current_time = get_beijing_time()
        webhook.last_triggered_at = current_time

        if success:
            webhook.last_success_at = current_time
            webhook.failure_count = 0
            webhook.next_retry_at = None
            webhook.last_failure_reason = None
            if webhook.status == "failed":
                webhook.status = "active"
        else:
            webhook.last_failure_at = current_time
            webhook.failure_count += 1
            webhook.last_failure_reason = failure_reason

            # 计算下次重试时间（指数退避）
            base_interval = 5  # 基础间隔5秒
            max_interval = 3600  # 最大间隔1小时
            retry_interval = min(
                base_interval * (2**webhook.failure_count), max_interval
            )
            webhook.next_retry_at = current_time + timedelta(seconds=retry_interval)

            # 如果失败次数超过阈值，标记为失败状态
            if webhook.failure_count >= 10:  # 最大重试10次
                webhook.status = "failed"

        webhook.updated_at = current_time

        db.add(webhook)
        db.commit()

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to update webhook status: {str(e)}")


def trigger_webhooks(
    db: Session,
    event: str,
    event_data: Dict[str, Any],
    data_types: Optional[List[str]] = None,
) -> None:
    """
    触发相关的WebHooks

    Args:
        db: 数据库会话
        event: 事件类型
        event_data: 事件数据
        data_types: 相关的数据类型列表
    """
    try:
        # 查找匹配的活跃WebHooks
        query = db.query(WebHook).filter(
            WebHook.status == "active",
            WebHook.events.contains(event),  # 检查事件类型匹配
        )

        # 如果指定了数据类型，则进一步过滤
        if data_types:
            # 使用OR条件匹配任何一个数据类型
            type_conditions = []
            for data_type in data_types:
                type_conditions.append(WebHook.types.contains(data_type))
            if type_conditions:
                if (
                    len(type_conditions) == 1
                ):  # 避免只有一个数据类型时产生不合法的查询语句
                    query = query.filter(type_conditions[0])
                else:
                    query = query.filter(or_(*type_conditions))

        webhooks = query.all()

        if not webhooks:
            logger.info(f"No active webhooks found for event: {event}")
            return

        # 异步发送WebHook通知
        def send_notification(webhook: WebHook):
            try:
                success = send_webhook_notification(webhook, event, event_data)
                update_webhook_status(
                    db,
                    webhook.id,
                    success,
                    None if success else "HTTP request failed",
                )
            except Exception as e:
                update_webhook_status(
                    db,
                    webhook.id,
                    False,
                    f"Exception: {str(e)}",
                )

        # 使用线程池异步发送通知
        with ThreadPoolExecutor(max_workers=5) as executor:
            for webhook in webhooks:
                executor.submit(send_notification, webhook)

        logger.info(f"Triggered {len(webhooks)} webhooks for event: {event}")

    except Exception as e:
        logger.error(f"Failed to trigger webhooks: {str(e)}")


def trigger_data_change_webhook(db: Session, data_types: List[str]) -> None:
    """
    通知发现服务器指定数据类型发生变化(data_change)
    并在短时间窗口内合并为批量通知(data_change)

    Args:
        db: 数据库会话
        data_types: 数据类型列表
    """
    try:
        batch_window = settings.DSP_WEBHOOK_BATCH_WINDOW_SECONDS
        if batch_window and batch_window > 0:
            # 启用批处理：不发送即时data_change，只合并到窗口后统一发送一次
            current_seq = get_current_max_seq(db)
            with _data_change_batch_lock:
                for t in data_types:
                    _data_change_batch_state["types"].add(t)
                # 记录窗口时间内的最大seq
                if _data_change_batch_state["max_seq"] is None:
                    _data_change_batch_state["max_seq"] = current_seq
                else:
                    _data_change_batch_state["max_seq"] = max(
                        _data_change_batch_state["max_seq"], current_seq
                    )

                # 重置定时器，静默期后执行批量发送
                timer: Timer = _data_change_batch_state.get("timer")
                if timer is not None:
                    timer.cancel()

                def _send_batch():
                    types_list: List[str]
                    max_seq_val: int
                    with _data_change_batch_lock:
                        types_list = list(_data_change_batch_state["types"]) or ["acs"]
                        max_seq_val = (
                            int(_data_change_batch_state["max_seq"])
                            if _data_change_batch_state["max_seq"] is not None
                            else 0
                        )

                        # 清空批处理状态
                        _data_change_batch_state["types"].clear()
                        _data_change_batch_state["max_seq"] = None
                        _data_change_batch_state["timer"] = None

                    try:
                        with SessionLocal() as tmp_db:
                            # 为每个数据类型发送单独的data_change事件
                            for data_type in types_list:
                                event_data = {
                                    "type": data_type,
                                    "current_seq": max_seq_val,
                                }
                                trigger_webhooks(
                                    db=tmp_db,
                                    event="data_change",
                                    event_data=event_data,
                                    data_types=[data_type],
                                )
                    except Exception:
                        logger.exception("Error sending data_change webhooks")

                new_timer = Timer(batch_window, _send_batch)
                _data_change_batch_state["timer"] = new_timer
                new_timer.daemon = True
                new_timer.start()
        else:
            # 未启用批处理：按类型即时发送 data_change
            current_seq = get_current_max_seq(db)
            for data_type in data_types:
                event_data = {"type": data_type, "current_seq": current_seq}
                trigger_webhooks(
                    db=db,
                    event="data_change",
                    event_data=event_data,
                    data_types=[data_type],
                )

    except Exception:
        logger.exception("Error triggering data_change webhooks")


def trigger_retention_cleanup_webhook(
    db: Session, cleaned_count: int, window_hours: int, max_records: int
) -> None:
    """
    在数据保留策略清理时触发WebHook

    Args:
        db: 数据库会话
        cleaned_count: 清理的记录数量
        window_hours: 保留窗口时长（小时）
        max_records: 保留的最大记录数
    """
    try:
        # 只有在实际清理了数据时才触发webhook
        if cleaned_count > 0:
            current_seq = get_current_max_seq(db)
            oldest_seq = get_retention_oldest_seq(db, window_hours, max_records)

            event_data = {
                "type": "acs",
                "cleaned_count": cleaned_count,
                "window_hours": window_hours,
                "max_records": max_records,
                "current_seq": current_seq,
                "oldest_seq": oldest_seq,
                "cleanup_timestamp": get_beijing_time().isoformat(),
            }

            trigger_webhooks(
                db=db,
                event="retention_cleanup",
                event_data=event_data,
                data_types=["acs"],
            )

            logger.info(
                f"Triggered retention_cleanup webhook for {cleaned_count} cleaned records"
            )
    except Exception:
        logger.exception("Error triggering retention_cleanup webhooks")
