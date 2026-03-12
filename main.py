from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.core.config import settings
from app.core.db_session import create_db_and_tables_async, async_engine, sync_engine
from app.core.base_exception import BaseException
from app.core.acps_exception import AcpsException
from app.utils.ip_restrict import parse_allowed_ips, create_ip_restriction_middleware

# Import API routers
from app.account.api_auth import router as auth_router
from app.account.api_account import router as account_router
from app.agent.api import router_public as agent_router_public
from app.agent.api import router_client as agent_router_client
from app.agent.api import router_staff as agent_router_staff
from app.agent.api_atr import router as agent_router_atr
from app.file.api import router as file_router
from app.sync.api import router as sync_router

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Parse ATR allowed IPs and create middleware
ATR_ALLOWED_NETWORKS = parse_allowed_ips(settings.ATR_ALLOW_IP_LIST)
atr_ip_restriction_middleware = create_ip_restriction_middleware(
    ATR_ALLOWED_NETWORKS, settings.ATR_BASE_PATH
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_db_and_tables_async()
    yield
    # Shutdown - properly close database connections
    await async_engine.dispose()
    sync_engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Agent Registration and Discovery System API",
    version="0.1.0",
    lifespan=lifespan,
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add ATR IP restriction middleware
app.middleware("http")(atr_ip_restriction_middleware)


# Global exception handler for BaseException
@app.exception_handler(BaseException)
async def my_exception_handler(request: Request, exc: BaseException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(AcpsException)
async def acps_exception_handler(request: Request, exc: AcpsException):
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_response_payload(),
    )


# Include API routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(account_router, prefix=settings.API_V1_STR)
app.include_router(agent_router_public, prefix=settings.API_V1_STR)
app.include_router(agent_router_client, prefix=settings.API_V1_STR)
app.include_router(agent_router_staff, prefix=settings.API_V1_STR)
app.include_router(
    agent_router_atr, prefix=settings.ATR_BASE_PATH
)  # ATR 路由，使用 ATR_BASE_PATH 配置
app.include_router(file_router, prefix=settings.API_V1_STR)
app.include_router(sync_router, prefix=settings.DSP_BASE_PATH, tags=["数据同步协议"])


@app.get("/")
async def root():
    return {
        "message": "Welcome to the Agent Internet Backend API",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.UVICORN_HOST,
        port=settings.UVICORN_PORT,
        reload=settings.UVICORN_RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL,
    )
