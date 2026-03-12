"""
后台任务：定期清理过期的Snapshot。
TODO: 需要在应用启动时注册此任务，并确保在应用关闭时正确停止。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.db_session import SessionLocal
from app.core.config import settings
from app.sync.service import cleanup_expired_snapshots
from app.utils.utils import get_beijing_time

logger = logging.getLogger(__name__)


class SnapshotCleanupTask:
    """定期清理过期Snapshot的后台任务"""

    def __init__(self):
        self.is_running = False
        self.cleanup_interval = (
            settings.DSP_SNAPSHOT_CLEANUP_INTERVAL_HOURS * 3600
        )  # 转换为秒

    async def start(self):
        """启动后台清理任务"""
        if self.is_running:
            logger.warning("Snapshot cleanup task is already running")
            return

        self.is_running = True
        logger.info(
            f"Starting snapshot cleanup task with interval: {settings.DSP_SNAPSHOT_CLEANUP_INTERVAL_HOURS} hours"
        )

        while self.is_running:
            try:
                await self._cleanup_expired_snapshots()
                await asyncio.sleep(self.cleanup_interval)
            except asyncio.CancelledError:
                logger.info("Snapshot cleanup task was cancelled")
                break
            except Exception as e:
                logger.error(f"Error in snapshot cleanup task: {str(e)}")
                # 出错后等待较短时间再重试
                await asyncio.sleep(300)  # 5分钟后重试

    async def stop(self):
        """停止后台清理任务"""
        self.is_running = False
        logger.info("Stopping snapshot cleanup task")

    async def _cleanup_expired_snapshots(self):
        """执行清理过期Snapshot的具体逻辑"""
        try:
            db = SessionLocal()
            try:
                cleaned_count = cleanup_expired_snapshots(db)
                if cleaned_count > 0:
                    logger.info(f"Cleaned up {cleaned_count} expired snapshots")
                else:
                    logger.debug("No expired snapshots found to clean up")
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Failed to cleanup expired snapshots: {str(e)}")


# 全局任务实例
snapshot_cleanup_task = SnapshotCleanupTask()


async def start_background_tasks():
    """启动所有后台任务"""
    logger.info("Starting background tasks...")

    # 创建清理任务
    cleanup_task = asyncio.create_task(snapshot_cleanup_task.start())

    return [cleanup_task]


async def stop_background_tasks():
    """停止所有后台任务"""
    logger.info("Stopping background tasks...")
    await snapshot_cleanup_task.stop()
