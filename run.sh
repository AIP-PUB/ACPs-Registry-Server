#!/usr/bin/env bash
set -euo pipefail

# ===========================================================================
# run.sh — 统一服务管理脚本
#
# 用法:
#   ./run.sh start               # 启动服务（若已运行则报错）
#   ./run.sh stop                # 停止服务
#   ./run.sh restart             # 重启服务（先停后启）
#   ./run.sh status              # 查看服务状态
#   ./run.sh kill-port [port]    # 按端口号杀死监听进程（PID文件丢失时的恢复手段）
#
# 日志输出到 logs/<SVC_NAME>.log，PID 记录在 logs/<SVC_NAME>.pid。
# ===========================================================================

# ===========================================================================
# 项目配置（适配不同项目时，只需修改此区域）
# ===========================================================================
PROJECT_NAME="registry-server"                    # 项目名称（仅用于显示）
SVC_NAME="server"                                 # 服务名（PID/日志文件前缀）
ENTRY_POINT="main.py"                             # 启动入口脚本
PORT_CONFIG_EXPR="settings.UVICORN_PORT"          # Python 表达式：从配置读取端口
DEFAULT_PORT="8001"                               # 配置读取失败时的回退端口
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-15}"           # 启动就绪超时（秒）

# ===========================================================================
# 以下为通用逻辑，各项目保持一致，无需修改
# ===========================================================================

ACTION="${1:-}"

# 验证参数
case "${ACTION}" in
  start|stop|restart|status|kill-port) ;;
  *)
    echo "用法: $0 {start|stop|restart|status|kill-port} [port]"
    echo ""
    echo "  start              启动服务（若已运行则报错）"
    echo "  stop               停止服务"
    echo "  restart            重启服务（先停后启）"
    echo "  status             查看服务状态"
    echo "  kill-port [port]   按端口号杀死监听进程（默认端口从配置读取）"
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# 基础设置
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

PID_FILE="$LOG_DIR/${SVC_NAME}.pid"
LOG_FILE="$LOG_DIR/${SVC_NAME}.log"

# 检测虚拟环境
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  VENV_DIR="$SCRIPT_DIR/.venv"
elif [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
  VENV_DIR="$SCRIPT_DIR/venv"
else
  echo "ERROR: 未找到虚拟环境 (.venv 或 venv)。"
  echo "请先创建虚拟环境并安装依赖。例如:"
  echo "  python3 -m venv venv"
  echo "  source venv/bin/activate"
  echo "  pip install poetry"
  echo "  poetry install"
  exit 1
fi
PYTHON_BIN="$VENV_DIR/bin/python"

# 从配置读取默认端口
get_configured_port() {
  PYTHONPATH="$SCRIPT_DIR" "$PYTHON_BIN" -c \
    "from app.core.config import settings; print($PORT_CONFIG_EXPR)" \
    2>/dev/null || echo "$DEFAULT_PORT"
}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

is_pid_alive() {
  local pid="$1"
  [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null
}

# 获取进程（含子进程）监听的所有端口，逗号分隔
# 优先使用 ss（Linux），回退到 lsof（macOS/通用）
get_listen_ports() {
  local pid="$1"
  local all_pids="$pid"
  local child_pids
  child_pids=$(pgrep -P "$pid" 2>/dev/null || true)
  if [ -n "${child_pids:-}" ]; then
    child_pids=$(echo "$child_pids" | tr '\n' ',' | sed 's/,$//')
    all_pids="$pid,$child_pids"
  fi

  if command -v ss >/dev/null 2>&1; then
    local p
    for p in $(echo "$all_pids" | tr ',' ' '); do
      ss -tlnp 2>/dev/null | awk -v pid="$p" '
        $0 ~ "pid="pid"[^0-9]" || $0 ~ "pid="pid"$" {
          n = split($4, a, ":"); print a[n]
        }'
    done | sort -un | tr '\n' ',' | sed 's/,$//'
    return 0
  elif command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$all_pids" -iTCP -sTCP:LISTEN -n -P 2>/dev/null \
      | awk 'NR>1 { split($9, a, ":"); print a[length(a)] }' \
      | sort -un \
      | tr '\n' ',' \
      | sed 's/,$//' \
      || true
    return 0
  fi
  return 0
}

# ---------------------------------------------------------------------------
# stop 操作
# ---------------------------------------------------------------------------

do_stop() {
  echo "=== 停止服务 ==="

  if [ ! -f "$PID_FILE" ]; then
    echo "[INFO] 未发现运行中的服务（无 PID 文件）。"
    return 0
  fi

  local pid
  pid=$(cat "$PID_FILE" 2>/dev/null || true)

  if [ -z "${pid:-}" ] || ! [[ "$pid" =~ ^[0-9]+$ ]]; then
    echo "[WARN] PID 文件无效（内容: '${pid:-}' ），清理"
    rm -f "$PID_FILE"
    return 0
  fi

  if ! is_pid_alive "$pid"; then
    echo "[INFO] PID:$pid 未运行，清理 PID 文件"
    rm -f "$PID_FILE"
    return 0
  fi

  echo "发送 SIGTERM -> $SVC_NAME (PID:$pid)"
  kill "$pid" 2>/dev/null || true

  # 等待退出
  local waited=0
  while is_pid_alive "$pid" && [ $waited -lt 10 ]; do
    sleep 1
    waited=$((waited+1))
  done

  if is_pid_alive "$pid"; then
    echo "[WARN] $SVC_NAME (PID:$pid) 未响应 SIGTERM，发送 SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
    sleep 0.5
  fi

  if is_pid_alive "$pid"; then
    echo "[FAIL] 无法停止 $SVC_NAME (PID:$pid)"
    return 1
  else
    echo "[OK] $SVC_NAME (PID:$pid) 已停止"
    rm -f "$PID_FILE"
    return 0
  fi
}

# ---------------------------------------------------------------------------
# start 操作
# ---------------------------------------------------------------------------

do_start() {
  echo "=== 启动服务 ==="

  if [ "${RESTART_MODE:-}" = true ]; then
    # restart 模式：先停掉旧进程
    if [ -f "$PID_FILE" ]; then
      local old_pid
      old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
      if [ -n "${old_pid:-}" ] && is_pid_alive "$old_pid"; then
        echo "检测到旧进程 (PID:$old_pid) 仍在运行，正在停止..."
        kill "$old_pid" 2>/dev/null || true
        local waited=0
        while is_pid_alive "$old_pid" && [ $waited -lt 5 ]; do
          sleep 1
          waited=$((waited+1))
        done
        if is_pid_alive "$old_pid"; then
          echo "旧进程 (PID:$old_pid) 未在 5s 内退出，发送 SIGKILL"
          kill -9 "$old_pid" 2>/dev/null || true
          sleep 1
        fi
        echo "旧进程已停止"
      fi
      rm -f "$PID_FILE"
    fi
  else
    # start 模式：若已运行则报错
    if [ -f "$PID_FILE" ]; then
      local old_pid
      old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
      if [ -n "${old_pid:-}" ] && is_pid_alive "$old_pid"; then
        echo "错误: 服务已在运行 (PID:$old_pid)。若要重启请使用: $0 restart"
        exit 1
      fi
      # PID 文件存在但进程已死，清理
      rm -f "$PID_FILE"
    fi
  fi

  # 检查 .env 文件
  if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "ERROR: 未找到 .env 配置文件。请先从 .env.example 复制并修改："
    echo "  cp .env.example .env"
    exit 1
  fi

  # 启动服务
  PYTHONPATH="$SCRIPT_DIR" nohup "$PYTHON_BIN" -u "$SCRIPT_DIR/$ENTRY_POINT" \
      >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"

  local pid
  pid=$(cat "$PID_FILE")
  echo "启动 $SVC_NAME ($ENTRY_POINT), PID: $pid, 日志: $LOG_FILE"

  # 等待就绪
  echo "等待服务就绪（超时 ${STARTUP_TIMEOUT}s）..."
  local waited=0
  while [ $waited -lt "$STARTUP_TIMEOUT" ]; do
    if ! is_pid_alive "$pid"; then
      echo "[FAIL] $SVC_NAME: 进程 PID:$pid 启动失败（请查看 ${LOG_FILE}）"
      rm -f "$PID_FILE"
      return 1
    fi

    local ports
    ports=$(get_listen_ports "$pid")
    if [ -n "${ports:-}" ]; then
      echo "[OK] $SVC_NAME: PID:$pid, 端口: $ports ($((waited))s)"
      return 0
    fi

    sleep 1
    waited=$((waited+1))
    printf '.'  # 显示等待进度
  done
  echo ''  # 换行

  # 超时但进程还活着
  echo "[WARN] $SVC_NAME: PID:$pid 存活，但 ${STARTUP_TIMEOUT}s 内未检测到端口（lsof 不可用或启动较慢）"
  return 0
}

# ---------------------------------------------------------------------------
# status 操作
# ---------------------------------------------------------------------------

do_status() {
  echo "=== 服务状态 ==="
  if [ ! -f "$PID_FILE" ]; then
    echo "[--] $SVC_NAME: 未启动（无 PID 文件）"
    return 0
  fi

  local pid
  pid=$(cat "$PID_FILE" 2>/dev/null || true)

  if [ -z "${pid:-}" ] || ! [[ "$pid" =~ ^[0-9]+$ ]]; then
    echo "[--] $SVC_NAME: PID 文件无效（内容: '${pid:-}' ）"
    return 0
  fi

  if ! is_pid_alive "$pid"; then
    echo "[STOP] $SVC_NAME: PID:$pid 未存活"
    return 0
  fi

  local ports
  ports=$(get_listen_ports "$pid")
  if [ -n "${ports:-}" ]; then
    echo "[RUN] $SVC_NAME: PID:$pid, 端口: $ports"
  else
    echo "[RUN] $SVC_NAME: PID:${pid}（端口未知）"
  fi
}

# ---------------------------------------------------------------------------
# kill-port 操作
# ---------------------------------------------------------------------------

# 按端口号查找监听进程的 PID（优先 ss，回退 lsof）
find_pids_by_port() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null \
      | awk -v port="$port" '{
          n = split($4, a, ":");
          if (a[n] == port) {
            # 从 users 列提取 pid
            gsub(/.*pid=/, "", $0); gsub(/[^0-9].*/, "", $0);
            if ($0 ~ /^[0-9]+$/) print $0
          }
        }' | sort -un || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -un || true
  fi
}

do_kill_port() {
  shift  # 跳过 ACTION 参数

  local port_list=()
  if [ $# -eq 0 ]; then
    local default_port
    default_port=$(get_configured_port)
    port_list=("$default_port")
    echo "未指定端口，使用配置端口: ${port_list[*]}"
  else
    port_list=("$@")
  fi

  local ok_count=0 fail_count=0

  for port in "${port_list[@]}"; do
    # 校验端口号格式
    if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
      echo "[ERROR] 无效端口号: ${port}（需为 1-65535 的整数）"
      fail_count=$((fail_count+1))
      continue
    fi

    echo "--- 端口 $port ---"
    local pids
    pids=$(find_pids_by_port "$port")

    if [ -z "${pids:-}" ]; then
      echo "[INFO] 端口 $port 上未发现监听进程"
      ok_count=$((ok_count+1))
      continue
    fi

    for pid in $pids; do
      local cmd_info
      cmd_info=$(ps -p "$pid" -o pid=,args= 2>/dev/null || echo "$pid (信息不可用)")
      echo "发现进程: $cmd_info"
      echo "发送 SIGTERM -> PID:$pid"
      kill "$pid" 2>/dev/null || true
    done

    # 等待进程退出
    local waited=0
    while [ $waited -lt 5 ]; do
      local still_alive=false
      for pid in $pids; do
        if is_pid_alive "$pid"; then
          still_alive=true
          break
        fi
      done
      $still_alive || break
      sleep 1
      waited=$((waited+1))
    done

    # 检查并强杀
    local port_ok=true
    for pid in $pids; do
      if is_pid_alive "$pid"; then
        echo "[WARN] PID:$pid 未响应 SIGTERM，发送 SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
        sleep 0.5
        if is_pid_alive "$pid"; then
          echo "[FAIL] 无法杀死 PID:$pid"
          port_ok=false
        else
          echo "[OK] PID:$pid 已强制停止"
        fi
      else
        echo "[OK] PID:$pid 已停止"
      fi
    done

    if $port_ok; then
      ok_count=$((ok_count+1))
    else
      fail_count=$((fail_count+1))
    fi
  done

  printf "\n结果: OK=%s, FAIL=%s\n" "$ok_count" "$fail_count"
  [ $fail_count -eq 0 ]
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

case "$ACTION" in
  start)     do_start ;;
  stop)      do_stop ;;
  restart)   RESTART_MODE=true; do_start ;;
  status)    do_status ;;
  kill-port) do_kill_port "$@" ;;
esac
