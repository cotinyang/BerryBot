#!/usr/bin/env bash
# 语音助手客户端管理脚本 (树莓派 3B)
# 用法: ./start.sh {start|stop|restart|status|logs}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="${SCRIPT_DIR}/client.pid"
LOG_FILE="${SCRIPT_DIR}/client.log"
APP_NAME="voice-assistant-client"

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
SERVER_URL="${SERVER_URL:?SERVER_URL is required}"
AUTH_TOKEN="${AUTH_TOKEN:?AUTH_TOKEN is required}"
WAKE_WORD_ENGINE="${WAKE_WORD_ENGINE:-sherpa_onnx}"
WAKE_WORD_ACCESS_KEY="${WAKE_WORD_ACCESS_KEY:-}"
WAKE_WORD_KEYWORD_PATH="${WAKE_WORD_KEYWORD_PATH:-}"
WAKE_WORD_KEYWORDS="${WAKE_WORD_KEYWORDS:-小艺小艺}"
WAKE_WORD_MODEL_PATH="${WAKE_WORD_MODEL_PATH:-}"
WAKE_PROMPT_AUDIO="${WAKE_PROMPT_AUDIO:-assets/wo_zai.mp3}"
WAKE_PROMPT_DELAY="${WAKE_PROMPT_DELAY:-0.3}"
SILENCE_THRESHOLD="${SILENCE_THRESHOLD:-1.5}"
SAMPLE_RATE="${SAMPLE_RATE:-16000}"
ENERGY_THRESHOLD="${ENERGY_THRESHOLD:-500.0}"
RECONNECT_INTERVAL="${RECONNECT_INTERVAL:-5.0}"
MAX_RECONNECT_RETRIES="${MAX_RECONNECT_RETRIES:-3}"
SESSION_TIMEOUT="${SESSION_TIMEOUT:-5.0}"
SESSION_END_AUDIO="${SESSION_END_AUDIO:-assets/end.wav}"
AUDIO_PLAYER_COMMAND="${AUDIO_PLAYER_COMMAND:-}"
AUDIO_OUTPUT_DEVICE="${AUDIO_OUTPUT_DEVICE:-}"

# 将相对路径解析到脚本目录，避免从其它 cwd 启动时找不到资产文件
if [[ "$WAKE_PROMPT_AUDIO" != /* ]]; then
    WAKE_PROMPT_AUDIO="${SCRIPT_DIR}/${WAKE_PROMPT_AUDIO}"
fi
if [[ "$SESSION_END_AUDIO" != /* ]]; then
    SESSION_END_AUDIO="${SCRIPT_DIR}/${SESSION_END_AUDIO}"
fi

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
    local -a extra_args=()
    if [ -n "$AUDIO_PLAYER_COMMAND" ]; then
        extra_args+=(--audio-player-command "$AUDIO_PLAYER_COMMAND")
        echo "  Audio player command override enabled"
    fi
    if [ -n "$AUDIO_OUTPUT_DEVICE" ]; then
        extra_args+=(--audio-output-device "$AUDIO_OUTPUT_DEVICE")
        echo "  Audio output device: ${AUDIO_OUTPUT_DEVICE}"
    fi

    nohup uv run python -m client.main \
        --server-url "$SERVER_URL" \
        --auth-token "$AUTH_TOKEN" \
        --wake-word-engine "$WAKE_WORD_ENGINE" \
        --wake-word-access-key "$WAKE_WORD_ACCESS_KEY" \
        --wake-word-keyword-path "$WAKE_WORD_KEYWORD_PATH" \
        --wake-word-keywords "$WAKE_WORD_KEYWORDS" \
        --wake-word-model-path "$WAKE_WORD_MODEL_PATH" \
        --wake-prompt-audio-path "$WAKE_PROMPT_AUDIO" \
        --wake-prompt-delay "$WAKE_PROMPT_DELAY" \
        --silence-threshold "$SILENCE_THRESHOLD" \
        --sample-rate "$SAMPLE_RATE" \
        --energy-threshold "$ENERGY_THRESHOLD" \
        --reconnect-interval "$RECONNECT_INTERVAL" \
        --max-reconnect-retries "$MAX_RECONNECT_RETRIES" \
        --session-timeout "$SESSION_TIMEOUT" \
        --session-end-audio-path "$SESSION_END_AUDIO" \
        "${extra_args[@]}" \
        >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
        echo "${APP_NAME} started (pid: ${pid})"
        echo "  Log: ${LOG_FILE}"
        echo "  Server: ${SERVER_URL}"
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
