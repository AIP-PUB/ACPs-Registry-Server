from datetime import datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field, ConfigDict


class Envelope(BaseModel):
    """数据同步协议的信封格式"""

    seq: int = Field(..., description="全局递增序号")
    ts: Optional[datetime] = Field(None, description="变更时间戳")
    op: Optional[str] = Field(
        "upsert", description="操作类型：upsert或delete，缺省为upsert"
    )
    type: str = Field(..., description="对象类型")
    id: str = Field(..., description="对象全局唯一ID")
    version: int = Field(..., description="对象版本号")
    payload: Optional[Dict[str, Any]] = Field(None, description="实际数据")

    model_config = ConfigDict(from_attributes=True)


class ChangeLogResponse(BaseModel):
    """变更日志响应模型"""

    seq: int
    ts: datetime
    type: str
    id: str
    version: int
    payload: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class SnapshotResponse(BaseModel):
    """快照响应模型"""

    snapshot_id: str = Field(..., description="快照唯一标识符")
    snapshot_seq: int = Field(..., description="快照对应的序列号")
    chunk_index: int = Field(..., description="当前块索引")
    chunk_total: int = Field(..., description="总块数")
    object_count: int = Field(..., description="快照包含的总对象数量")

    model_config = ConfigDict(from_attributes=True)


class SnapshotInfo(BaseModel):
    """快照信息模型"""

    id: str = Field(..., description="快照唯一标识符")
    types: str = Field(..., description="数据类型")
    seq: int = Field(..., description="快照切点序列号")
    chunk_total: int = Field(..., description="总块数")
    object_count: int = Field(..., description="对象总数")
    from_seq: Optional[int] = Field(None, description="增量快照起始序列号")
    is_deleted: bool = Field(..., description="是否已删除")
    created_at: datetime = Field(..., description="创建时间")
    last_access_at: datetime = Field(..., description="最后访问时间")
    expire_at: datetime = Field(..., description="过期时间")

    model_config = ConfigDict(from_attributes=True)


class ChangesRequest(BaseModel):
    """增量变更请求模型"""

    types: Optional[str] = Field(None, description="数据类型，逗号分隔")
    seq: Optional[int] = Field(None, description="起始序列号")
    limit: int = Field(1000, description="返回条数限制")
    wait: Optional[str] = Field(None, description="长轮询等待时间")

    model_config = ConfigDict(from_attributes=True)


class SnapshotRequest(BaseModel):
    """快照请求模型"""

    types: Optional[str] = Field(None, description="数据类型，逗号分隔")
    limit: int = Field(10000, description="每块最大对象数量")
    from_seq: Optional[int] = Field(None, description="增量快照的起始序号")
    snapshot_id: Optional[str] = Field(None, description="快照ID，用于获取后续块")
    chunk: Optional[int] = Field(None, description="块索引")

    model_config = ConfigDict(from_attributes=True)


class InfoResponse(BaseModel):
    """系统信息响应模型 - 严格遵循 DSP 协议规范"""

    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="服务版本号")
    status: str = Field(..., description="服务健康状态")
    supported_types: list = Field(..., description="支持的对象类型列表")
    retention: Dict[str, Any] = Field(..., description="数据保留配置")
    snapshot: Dict[str, Any] = Field(..., description="快照配置")
    changes: Dict[str, Any] = Field(..., description="变更流配置")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "service": "agent-registry",
                "version": "1.0.0",
                "status": "healthy",
                "supported_types": ["acs"],
                "retention": {
                    "window_hours": 168,
                    "oldest_seq": 35000,
                    "newest_seq": 42789,
                },
                "snapshot": {
                    "access_timeout_hours": 2,
                    "max_lifetime_hours": 24,
                    "supports_incremental": True,
                    "supports_chunking": True,
                },
                "changes": {"supports_long_polling": False, "payload_type": "FULL_OBJ"},
            }
        },
    )


# WebHook 相关的 Schema


class WebHookCreate(BaseModel):
    """创建WebHook的请求模型"""

    url: str = Field(..., max_length=2000, description="回调URL")
    secret: str = Field(..., max_length=500, description="签名密钥")
    types: List[str] = Field(..., description="关注的数据类型列表")
    events: List[str] = Field(..., description="关注的事件类型列表")
    description: Optional[str] = Field(None, max_length=500, description="WebHook描述")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "url": "https://discovery.example.com/webhook/data-change",
                "secret": "shared-secret-key",
                "types": ["acs", "dataset"],
                "events": ["data_change", "retention_cleanup"],
                "description": "Discovery service webhook",
            }
        },
    )


class WebHookUpdate(BaseModel):
    """更新WebHook的请求模型"""

    url: Optional[str] = Field(None, max_length=2000, description="回调URL")
    secret: Optional[str] = Field(None, max_length=500, description="签名密钥")
    types: Optional[List[str]] = Field(None, description="关注的数据类型列表")
    events: Optional[List[str]] = Field(None, description="关注的事件类型列表")
    description: Optional[str] = Field(None, max_length=500, description="WebHook描述")

    model_config = ConfigDict(from_attributes=True)


class WebHookResponse(BaseModel):
    """WebHook响应模型"""

    id: str = Field(..., description="WebHook唯一标识")
    url: str = Field(..., description="回调URL")
    types: List[str] = Field(..., description="关注的数据类型列表")
    events: List[str] = Field(..., description="关注的事件类型列表")
    description: Optional[str] = Field(None, description="WebHook描述")
    status: str = Field(..., description="WebHook状态")
    failure_count: int = Field(..., description="失败计数")
    last_triggered_at: Optional[datetime] = Field(None, description="最后触发时间")
    last_success_at: Optional[datetime] = Field(None, description="最后成功时间")
    last_failure_at: Optional[datetime] = Field(None, description="最后失败时间")
    next_retry_at: Optional[datetime] = Field(None, description="下次重试时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "wh_abc123def456",
                "url": "https://discovery.example.com/webhook/data-change",
                "types": ["acs", "dataset"],
                "events": ["data_change", "retention_cleanup"],
                "description": "Discovery service webhook",
                "status": "active",
                "failure_count": 0,
                "last_triggered_at": "2025-08-19T12:15:30Z",
                "last_success_at": "2025-08-19T12:15:30Z",
                "last_failure_at": None,
                "next_retry_at": None,
                "created_at": "2025-08-19T10:30:00Z",
            }
        },
    )


class WebHookNotification(BaseModel):
    """WebHook回调通知的载荷模型"""

    id: str = Field(..., description="WebHook ID")
    event: str = Field(..., description="事件类型")
    timestamp: datetime = Field(..., description="事件时间戳")
    data: Dict[str, Any] = Field(..., description="事件数据")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "wh_abc123def456",
                "event": "data_change",
                "timestamp": "2025-08-19T12:15:30Z",
                "data": {"type": "acs", "current_seq": 42789},
            }
        },
    )


class WebHookCallbackResponse(BaseModel):
    """WebHook回调成功响应模型"""

    status: str = Field(..., description="处理状态")
    processed_at: datetime = Field(..., description="处理时间")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "status": "acknowledged",
                "processed_at": "2025-08-19T12:15:35Z",
            }
        },
    )
