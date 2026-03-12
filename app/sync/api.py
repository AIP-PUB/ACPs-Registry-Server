from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, Query, status, Header, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
import asyncio

from app.core.db_session import get_db
from app.core.config import settings
from app.sync.service import (
    get_changes,
    get_changelog_list,
    get_current_max_seq,
    get_retention_oldest_seq,
    cleanup_old_changelog_entries,
    create_changelog_response,
    create_snapshot,
    get_snapshot_chunk,
    delete_snapshot,
    get_snapshot_info,
    cleanup_expired_snapshots,
    create_webhook,
    get_webhook,
    update_webhook,
    delete_webhook,
    reactivate_webhook,
    get_webhook_list,
)
from app.sync.schema import (
    Envelope,
    ChangeLogResponse,
    ChangesRequest,
    SnapshotRequest,
    InfoResponse,
    SnapshotInfo,
    WebHookCreate,
    WebHookUpdate,
    WebHookResponse,
)
from app.sync.exception import SyncException, SyncError
from app.sync.model import Snapshot

router = APIRouter()


@router.get("/info", response_model=InfoResponse)
async def get_info(db: Session = Depends(get_db)):
    """获取系统信息和配置"""
    try:
        max_seq = get_current_max_seq(db)

        # 根据 DSP 协议规范计算 oldest_seq
        oldest_seq = get_retention_oldest_seq(
            db, settings.DSP_RETENTION_WINDOW_HOURS, settings.DSP_RETENTION_MAX_RECORDS
        )

        info = InfoResponse(
            service=settings.PROJECT_NAME,
            version=settings.PROJECT_VERSION,
            status="healthy",
            supported_types=["acs"],  # 根据 DSP 协议，目前只支持 acs 类型
            retention={
                "window_hours": settings.DSP_RETENTION_WINDOW_HOURS,
                "oldest_seq": oldest_seq,
                "newest_seq": max_seq,
            },
            snapshot={
                "access_timeout_hours": settings.DSP_SNAPSHOT_ACCESS_TIMEOUT_HOURS,
                "max_lifetime_hours": settings.DSP_SNAPSHOT_MAX_LIFETIME_HOURS,
                "supports_incremental": True,
                "supports_chunking": True,
            },
            changes={
                "supports_long_polling": False,  # 暂不支持长轮询
                "payload_type": "FULL_OBJ",  # 根据 DSP 协议，使用完整对象
            },
        )
        return info

    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to get system info: {str(e)}",
            input_params={},
        )


@router.get("/changes")
async def get_changes_api(
    response: Response,
    types: Optional[str] = Query(None, description="数据类型，逗号分隔"),
    seq: Optional[int] = Query(None, description="起始序列号"),
    limit: int = Query(settings.DSP_CHANGES_DEFAULT_LIMIT, description="返回条数限制"),
    wait: Optional[str] = Query(None, description="长轮询等待时间（秒）"),
    db: Session = Depends(get_db),
):
    """获取增量变更数据，支持长轮询"""
    try:
        # 验证limit参数范围
        if limit > settings.DSP_CHANGES_MAX_LIMIT:
            limit = settings.DSP_CHANGES_MAX_LIMIT
        elif limit <= 0:
            limit = settings.DSP_CHANGES_DEFAULT_LIMIT

        # 解析types参数
        type_list = None
        if types:
            type_list = [t.strip() for t in types.split(",")]

        # 解析wait参数
        wait_seconds = 0
        if wait:
            try:
                wait_seconds = int(float(wait))
                if wait_seconds < 0:
                    wait_seconds = 0
            except Exception:
                wait_seconds = 0

        poll_interval = 1  # 每次轮询间隔（秒）
        waited = 0

        while True:
            envelopes, next_seq = get_changes(
                db=db, seq=seq, limit=limit, types=type_list
            )

            if envelopes or wait_seconds == 0:
                # 有数据或不需要长轮询，直接返回
                response.headers["X-Next-Seq"] = str(next_seq)
                response.headers["Content-Type"] = "application/x-ndjson"

                if not envelopes:
                    response.status_code = status.HTTP_204_NO_CONTENT
                    return ""

                def generate_ndjson():
                    for envelope in envelopes:
                        yield envelope.model_dump_json(exclude_none=True) + "\n"

                return StreamingResponse(
                    generate_ndjson(),
                    media_type="application/x-ndjson",
                    headers={"X-Next-Seq": str(next_seq)},
                )

            # 没有数据且需要长轮询
            if waited >= wait_seconds:
                # 超时，返回204
                response.headers["X-Next-Seq"] = str(next_seq)
                response.status_code = status.HTTP_204_NO_CONTENT
                return ""
            await asyncio.sleep(poll_interval)
            waited += poll_interval

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to get changes: {str(e)}",
            input_params={"types": types, "seq": seq, "limit": limit, "wait": wait},
        )


@router.get("/snapshots")
async def get_snapshot_api(
    response: Response,
    types: Optional[str] = Query(None, description="数据类型，逗号分隔"),
    limit: int = Query(10000, description="每块最大对象数量"),
    from_seq: Optional[int] = Query(None, description="增量快照的起始序号"),
    id: Optional[str] = Query(None, description="快照ID，用于获取后续块"),
    chunk: Optional[int] = Query(None, description="块索引"),
    db: Session = Depends(get_db),
):
    """创建快照或获取快照数据"""
    try:
        # 参数验证
        if id and chunk is None:
            raise SyncException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=SyncError.INVALID_SNAPSHOT_PARAMS,
                error_msg="chunk parameter is required when id is provided",
                input_params={"id": id, "chunk": chunk},
            )

        if not id and not types:
            raise SyncException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=SyncError.INVALID_SNAPSHOT_PARAMS,
                error_msg="types parameter is required when creating a new snapshot",
                input_params={"types": types},
            )

        # 获取已存在的快照chunk
        if id:
            snapshot, envelopes = get_snapshot_chunk(
                db=db, snapshot_id=id, chunk_index=chunk, limit=limit
            )

            # 设置响应头
            response.headers["X-Snapshot-Id"] = snapshot.id
            response.headers["X-Snapshot-Seq"] = str(snapshot.seq)
            response.headers["X-Snapshot-Chunk-Index"] = str(chunk)
            response.headers["X-Snapshot-Chunk-Total"] = str(snapshot.chunk_total)
            response.headers["X-Snapshot-Object-Count"] = str(snapshot.object_count)
            response.headers["Content-Type"] = "application/x-ndjson"

        # 创建新的快照
        else:
            # 解析types参数
            type_list = [t.strip() for t in types.split(",") if t.strip()]
            if not type_list:
                raise SyncException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=SyncError.INVALID_SNAPSHOT_PARAMS,
                    error_msg="At least one data type must be specified",
                    input_params={"types": types},
                )

            # 验证数据类型（目前只支持acs）
            supported_types = ["acs"]
            invalid_types = [t for t in type_list if t not in supported_types]
            if invalid_types:
                raise SyncException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=SyncError.INVALID_SNAPSHOT_PARAMS,
                    error_msg=f"Unsupported data types: {invalid_types}. Supported types: {supported_types}",
                    input_params={"types": types, "invalid_types": invalid_types},
                )

            snapshot, envelopes = create_snapshot(
                db=db, types=type_list, limit=limit, from_seq=from_seq
            )

            # 设置响应头
            response.headers["X-Snapshot-Id"] = snapshot.id
            response.headers["X-Snapshot-Seq"] = str(snapshot.seq)
            response.headers["X-Snapshot-Chunk-Index"] = "0"
            response.headers["X-Snapshot-Chunk-Total"] = str(snapshot.chunk_total)
            response.headers["X-Snapshot-Object-Count"] = str(snapshot.object_count)
            response.headers["Content-Type"] = "application/x-ndjson"

        # 生成NDJSON格式的响应
        def generate_ndjson():
            for envelope in envelopes:
                yield envelope.model_dump_json(exclude_none=True) + "\n"

        return StreamingResponse(
            generate_ndjson(),
            media_type="application/x-ndjson",
            headers={
                "X-Snapshot-Id": response.headers["X-Snapshot-Id"],
                "X-Snapshot-Seq": response.headers["X-Snapshot-Seq"],
                "X-Snapshot-Chunk-Index": response.headers["X-Snapshot-Chunk-Index"],
                "X-Snapshot-Chunk-Total": response.headers["X-Snapshot-Chunk-Total"],
                "X-Snapshot-Object-Count": response.headers["X-Snapshot-Object-Count"],
            },
        )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_CREATE_FAILED,
            error_msg=f"Failed to process snapshot request: {str(e)}",
            input_params={
                "types": types,
                "limit": limit,
                "from_seq": from_seq,
                "id": id,
                "chunk": chunk,
            },
        )


@router.delete("/snapshots/{id}")
async def delete_snapshot_api(id: str, db: Session = Depends(get_db)):
    """删除指定的快照"""
    try:
        success = delete_snapshot(db=db, snapshot_id=id)
        if success:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        else:
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.SNAPSHOT_TABLE_DROP_FAILED,
                error_msg=f"Failed to delete snapshot {id}",
                input_params={"id": id},
            )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_TABLE_DROP_FAILED,
            error_msg=f"Failed to delete snapshot: {str(e)}",
            input_params={"id": id},
        )


# 内部管理API，用于查看变更日志
@router.get("/admin/changelogs", response_model=Dict[str, Any])
async def list_changelogs(
    page_num: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    object_id: Optional[str] = Query(None, description="对象ID"),
    data_type: Optional[str] = Query(None, description="数据类型"),
    db: Session = Depends(get_db),
):
    """获取变更日志列表（管理员接口）"""
    try:
        change_logs, total = get_changelog_list(
            db=db,
            page_num=page_num,
            page_size=page_size,
            object_id=object_id,
            data_type=data_type,
        )

        return {
            "items": [create_changelog_response(log) for log in change_logs],
            "total": total,
            "page_num": page_num,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to list changelogs: {str(e)}",
            input_params={
                "page_num": page_num,
                "page_size": page_size,
                "object_id": object_id,
                "data_type": data_type,
            },
        )


# 快照管理API
@router.get("/admin/snapshots", response_model=Dict[str, Any])
async def list_snapshots_api(
    page_num: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    include_deleted: bool = Query(False, description="是否包含已删除的快照"),
    db: Session = Depends(get_db),
):
    """获取快照列表（管理员接口）"""
    try:
        query = db.query(Snapshot)

        if not include_deleted:
            query = query.filter(Snapshot.is_deleted == False)

        # 获取总数
        total = query.count()

        # 计算分页偏移量
        skip = (page_num - 1) * page_size

        # 应用分页和排序
        snapshots = (
            query.order_by(Snapshot.created_at.desc())
            .offset(skip)
            .limit(page_size)
            .all()
        )

        return {
            "items": [SnapshotInfo.model_validate(s) for s in snapshots],
            "total": total,
            "page_num": page_num,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }

    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_DATA_QUERY_FAILED,
            error_msg=f"Failed to list snapshots: {str(e)}",
            input_params={
                "page_num": page_num,
                "page_size": page_size,
                "include_deleted": include_deleted,
            },
        )


@router.get("/admin/snapshots/{id}", response_model=SnapshotInfo)
async def get_snapshot_info_api(id: str, db: Session = Depends(get_db)):
    """获取快照信息（管理员接口）"""
    try:
        return get_snapshot_info(db=db, snapshot_id=id)
    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_DATA_QUERY_FAILED,
            error_msg=f"Failed to get snapshot info: {str(e)}",
            input_params={"id": id},
        )


@router.post("/admin/snapshots/cleanup")
async def cleanup_snapshots_api(db: Session = Depends(get_db)):
    """清理过期快照（管理员接口）"""
    try:
        cleaned_count = cleanup_expired_snapshots(db=db)
        return {"cleaned_count": cleaned_count}
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.SNAPSHOT_TABLE_DROP_FAILED,
            error_msg=f"Failed to cleanup expired snapshots: {str(e)}",
            input_params={},
        )


@router.post("/admin/changelogs/cleanup")
async def cleanup_changelogs_api(db: Session = Depends(get_db)):
    """根据retention配置清理旧的ChangeLog记录（管理员接口）"""
    try:
        cleaned_count = cleanup_old_changelog_entries(
            db=db,
            window_hours=settings.DSP_RETENTION_WINDOW_HOURS,
            max_records=settings.DSP_RETENTION_MAX_RECORDS,
        )
        return {
            "cleaned_count": cleaned_count,
            "retention_config": {
                "window_hours": settings.DSP_RETENTION_WINDOW_HOURS,
                "max_records": settings.DSP_RETENTION_MAX_RECORDS,
            },
        }
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.CHANGES_QUERY_FAILED,
            error_msg=f"Failed to cleanup old changelogs: {str(e)}",
            input_params={},
        )


# WebHook API endpoints


@router.post("/webhooks", response_model=WebHookResponse, status_code=201)
async def create_webhook_api(
    webhook_data: WebHookCreate,
    db: Session = Depends(get_db),
):
    """创建新的WebHook"""
    try:
        # 验证数据类型（目前只支持acs）
        supported_types = ["acs"]
        invalid_types = [t for t in webhook_data.types if t not in supported_types]
        if invalid_types:
            raise SyncException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=SyncError.WEBHOOK_INVALID_TYPES,
                error_msg=f"Unsupported data types: {invalid_types}. Supported types: {supported_types}",
                input_params={
                    "types": webhook_data.types,
                    "invalid_types": invalid_types,
                },
            )

        # 验证事件类型
        supported_events = [
            "data_change",
            "retention_cleanup",
            "service_maintenance",
            "service_healthy",
        ]
        invalid_events = [e for e in webhook_data.events if e not in supported_events]
        if invalid_events:
            raise SyncException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=SyncError.WEBHOOK_INVALID_EVENTS,
                error_msg=f"Unsupported event types: {invalid_events}. Supported events: {supported_events}",
                input_params={
                    "events": webhook_data.events,
                    "invalid_events": invalid_events,
                },
            )

        webhook = create_webhook(
            db=db,
            url=webhook_data.url,
            secret=webhook_data.secret,
            types=webhook_data.types,
            events=webhook_data.events,
            description=webhook_data.description,
        )

        # 转换响应格式
        return WebHookResponse(
            id=webhook.id,
            url=webhook.url,
            types=webhook.types.split(",") if webhook.types else [],
            events=webhook.events.split(",") if webhook.events else [],
            description=webhook.description,
            status=webhook.status,
            failure_count=webhook.failure_count,
            last_triggered_at=webhook.last_triggered_at,
            last_success_at=webhook.last_success_at,
            last_failure_at=webhook.last_failure_at,
            next_retry_at=webhook.next_retry_at,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_CREATE_FAILED,
            error_msg=f"Failed to create webhook: {str(e)}",
            input_params=webhook_data.model_dump(),
        )


@router.get("/webhooks/{id}", response_model=WebHookResponse)
async def get_webhook_api(id: str, db: Session = Depends(get_db)):
    """获取指定WebHook的信息"""
    try:
        webhook = get_webhook(db=db, webhook_id=id)

        return WebHookResponse(
            id=webhook.id,
            url=webhook.url,
            types=webhook.types.split(",") if webhook.types else [],
            events=webhook.events.split(",") if webhook.events else [],
            description=webhook.description,
            status=webhook.status,
            failure_count=webhook.failure_count,
            last_triggered_at=webhook.last_triggered_at,
            last_success_at=webhook.last_success_at,
            last_failure_at=webhook.last_failure_at,
            next_retry_at=webhook.next_retry_at,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_QUERY_FAILED,
            error_msg=f"Failed to get webhook: {str(e)}",
            input_params={"id": id},
        )


@router.put("/webhooks/{id}", response_model=WebHookResponse)
async def update_webhook_api(
    id: str,
    webhook_update: WebHookUpdate,
    db: Session = Depends(get_db),
):
    """更新指定WebHook的配置"""
    try:
        # 验证数据类型（如果提供）
        if webhook_update.types is not None:
            supported_types = ["acs"]
            invalid_types = [
                t for t in webhook_update.types if t not in supported_types
            ]
            if invalid_types:
                raise SyncException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=SyncError.WEBHOOK_INVALID_TYPES,
                    error_msg=f"Unsupported data types: {invalid_types}. Supported types: {supported_types}",
                    input_params={
                        "types": webhook_update.types,
                        "invalid_types": invalid_types,
                    },
                )

        # 验证事件类型（如果提供）
        if webhook_update.events is not None:
            supported_events = [
                "data_change",
                "retention_cleanup",
                "service_maintenance",
                "service_healthy",
            ]
            invalid_events = [
                e for e in webhook_update.events if e not in supported_events
            ]
            if invalid_events:
                raise SyncException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=SyncError.WEBHOOK_INVALID_EVENTS,
                    error_msg=f"Unsupported event types: {invalid_events}. Supported events: {supported_events}",
                    input_params={
                        "events": webhook_update.events,
                        "invalid_events": invalid_events,
                    },
                )

        webhook = update_webhook(
            db=db,
            webhook_id=id,
            url=webhook_update.url,
            secret=webhook_update.secret,
            types=webhook_update.types,
            events=webhook_update.events,
            description=webhook_update.description,
        )

        return WebHookResponse(
            id=webhook.id,
            url=webhook.url,
            types=webhook.types.split(",") if webhook.types else [],
            events=webhook.events.split(",") if webhook.events else [],
            description=webhook.description,
            status=webhook.status,
            failure_count=webhook.failure_count,
            last_triggered_at=webhook.last_triggered_at,
            last_success_at=webhook.last_success_at,
            last_failure_at=webhook.last_failure_at,
            next_retry_at=webhook.next_retry_at,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_UPDATE_FAILED,
            error_msg=f"Failed to update webhook: {str(e)}",
            input_params={"id": id, **webhook_update.model_dump()},
        )


@router.delete("/webhooks/{id}")
async def delete_webhook_api(id: str, db: Session = Depends(get_db)):
    """删除指定的WebHook"""
    try:
        success = delete_webhook(db=db, webhook_id=id)
        if success:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        else:
            raise SyncException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_name=SyncError.WEBHOOK_DELETE_FAILED,
                error_msg=f"Failed to delete webhook {id}",
                input_params={"id": id},
            )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_DELETE_FAILED,
            error_msg=f"Failed to delete webhook: {str(e)}",
            input_params={"id": id},
        )


@router.post("/webhooks/{id}/reactivate", response_model=WebHookResponse)
async def reactivate_webhook_api(id: str, db: Session = Depends(get_db)):
    """重新激活失败的WebHook"""
    try:
        webhook = reactivate_webhook(db=db, webhook_id=id)

        return WebHookResponse(
            id=webhook.id,
            url=webhook.url,
            types=webhook.types.split(",") if webhook.types else [],
            events=webhook.events.split(",") if webhook.events else [],
            description=webhook.description,
            status=webhook.status,
            failure_count=webhook.failure_count,
            last_triggered_at=webhook.last_triggered_at,
            last_success_at=webhook.last_success_at,
            last_failure_at=webhook.last_failure_at,
            next_retry_at=webhook.next_retry_at,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    except SyncException:
        raise
    except Exception as e:
        raise SyncException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_name=SyncError.WEBHOOK_REACTIVATE_FAILED,
            error_msg=f"Failed to reactivate webhook: {str(e)}",
            input_params={"id": id},
        )


@router.get("/webhooks", response_model=Dict[str, Any])
async def list_webhooks_api(
    page_num: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    status_filter: Optional[str] = Query(None, description="状态过滤"),
    db: Session = Depends(get_db),
):
    """获取WebHook列表"""
    try:
        webhooks, total = get_webhook_list(
            db=db,
            page_num=page_num,
            page_size=page_size,
            status_filter=status_filter,
        )

        # 转换响应格式
        webhook_responses = []
        for webhook in webhooks:
            webhook_responses.append(
                WebHookResponse(
                    id=webhook.id,
                    url=webhook.url,
                    types=webhook.types.split(",") if webhook.types else [],
                    events=webhook.events.split(",") if webhook.events else [],
                    description=webhook.description,
                    status=webhook.status,
                    failure_count=webhook.failure_count,
                    last_triggered_at=webhook.last_triggered_at,
                    last_success_at=webhook.last_success_at,
                    last_failure_at=webhook.last_failure_at,
                    next_retry_at=webhook.next_retry_at,
                    created_at=webhook.created_at,
                    updated_at=webhook.updated_at,
                )
            )

        return {
            "items": webhook_responses,
            "total": total,
            "page_num": page_num,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }

    except SyncException:
        raise
    except Exception as e:
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
