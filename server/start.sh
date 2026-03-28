#!/usr/bin/env bash
# 语音助手服务端管理脚本 (VPS Debian)
# 用法: ./start.sh {start|stop|restart|status|logs}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="${SCRIPT_DIR}/server.pid"
LOG_FILE="${SCRIPT_DIR}/server.log"
APP_NAME="voice-assistant-server"

# ── 加载 .env 配置 ────────────────────────────────────
ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
else
    echo "Warning: ${ENV_FILE} not found. Copy .env.example to .env and configure it."
    echo "  cp ${SCRIPT_DIR}/.env.example ${ENV_FILE}"
    exit 1
fi

# ── 配置 ──────────────────────────────────────────────
TLS_CERT="${TLS_CERT:?TLS_CERT is required}"
TLS_KEY="${TLS_KEY:?TLS_KEY is required}"
AUTH_TOKEN="${AUTH_TOKEN:?AUTH_TOKEN is required}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8765}"
WHISPER_MODEL="${WHISPER_MODEL:-base}"
TTS_VOICE="${TTS_VOICE:-zh-CN-XiaoxiaoNeural}"
SOUL_PATH="${SOUL_PATH:-SOUL.md}"
MEMORY_PATH="${MEMORY_PATH:-MEMORY.md}"

# ── 函数 ──────────────────────────────────────────────

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    return 1
}

do_start() {
    if pid=$(get_pid); then
        echo "${APP_NAME} is already running (pid: ${pid})"
        exit 1
    fi

    echo "Starting ${APP_NAME}..."
    nohup uv run python -m server.main \
        --host "$HOST" \
        --port "$PORT" \
        --tls-cert "$TLS_CERT" \
        --tls-key "$TLS_KEY" \
        --auth-token "$AUTH_TOKEN" \
        --whisper-model "$WHISPER_MODEL" \
        --tts-voice "$TTS_VOICE" \
        --soul-path "$SOUL_PATH" \
        --memory-path "$MEMORY_PATH" \
        >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
        echo "${APP_NAME} started (pid: ${pid})"
        echo "  Log: ${LOG_FILE}"
        echo "  Listen: wss://${HOST}:${PORT}"
    else
        rm -f "$PID_FILE"
        echo "Failed to start ${APP_NAME}. Check ${LOG_FILE}"
        exit 1
    fi
}

do_stop() {
    if ! pid=$(get_pid); then
        echo "${APP_NAME} is not running"
        return 0
    fi

    echo "Stopping ${APP_NAME} (pid: ${pid})..."
    kill "$pid"

    local count=0
    while kill -0 "$pid" 2>/dev/null; do
        count=$((count + 1))
        if [ "$count" -ge 10 ]; then
            echo "Force killing ${APP_NAME}..."
            kill -9 "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
    done

    rm -f "$PID_FILE"
    echo "${APP_NAME} stopped"
}

do_status() {
    if pid=$(get_pid); then
        echo "${APP_NAME} is running (pid: ${pid})"
    else
        echo "${APP_NAME} is not running"
    fi
}

do_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "No log file found: ${LOG_FILE}"
        exit 1
    fi
    tail -f "$LOG_FILE"
}

# ── 入口 ──────────────────────────────────────────────

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)  do_status ;;
    logs)    do_logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
