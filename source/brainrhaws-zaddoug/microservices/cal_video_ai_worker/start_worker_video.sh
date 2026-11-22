#!/usr/bin/env sh
set -eu

log() {
  printf '[worker-video-entrypoint] %s\n' "$*"
}

display_value="${DISPLAY:-:99}"
case "$display_value" in
  :*) ;;
  *) display_value=":${display_value}" ;;
esac
display_number="${display_value#:}"
display_number="${display_number%%.*}"

export DISPLAY="$display_value"

lock_file="/tmp/.X${display_number}-lock"
socket_file="/tmp/.X11-unix/X${display_number}"
screen="${CAL_VIDEO_XVFB_SCREEN:-1280x720x24}"
wait_seconds="${CAL_VIDEO_XVFB_WAIT_SECONDS:-10}"
xvfb_pid=""
app_pid=""

cleanup() {
  if [ -n "$xvfb_pid" ] && kill -0 "$xvfb_pid" 2>/dev/null; then
    log "stopping Xvfb ${xvfb_pid}"
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
  fi
}

terminate() {
  if [ -n "$app_pid" ] && kill -0 "$app_pid" 2>/dev/null; then
    kill "$app_pid" 2>/dev/null || true
  fi
  cleanup
}

trap cleanup EXIT
trap terminate INT TERM

find_xvfb_pid() {
  ps -eo pid=,args= | awk -v display="$display_value" '
    $2 == "Xvfb" && $3 == display {
      print $1
      exit
    }
  '
}

display_ready() {
  if command -v xdpyinfo >/dev/null 2>&1; then
    DISPLAY="$display_value" xdpyinfo >/dev/null 2>&1
    return "$?"
  fi

  [ -S "$socket_file" ]
}

mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix

existing_xvfb_pid="$(find_xvfb_pid || true)"
if [ -z "$existing_xvfb_pid" ]; then
  if [ -e "$lock_file" ] || [ -S "$socket_file" ]; then
    log "removing stale X display artifacts for ${display_value}"
    rm -f "$lock_file" "$socket_file"
  fi

  log "starting Xvfb on ${display_value} (${screen})"
  Xvfb "$display_value" -screen 0 "$screen" -ac +extension RANDR -nolisten tcp &
  xvfb_pid="$!"
else
  log "using existing Xvfb process ${existing_xvfb_pid} on ${display_value}"
fi

elapsed=0
while [ "$elapsed" -lt "$wait_seconds" ]; do
  if [ -n "$xvfb_pid" ] && ! kill -0 "$xvfb_pid" 2>/dev/null; then
    log "Xvfb exited before ${display_value} became ready"
    wait "$xvfb_pid" || true
    exit 1
  fi

  if display_ready; then
    log "X display ${display_value} is ready"
    python -m brainrh.worker.cal_video_worker_service &
    app_pid="$!"
    set +e
    wait "$app_pid"
    status="$?"
    set -e
    exit "$status"
  fi

  elapsed=$((elapsed + 1))
  sleep 1
done

log "X display ${display_value} did not become ready after ${wait_seconds}s"
if [ -n "$xvfb_pid" ]; then
  kill "$xvfb_pid" 2>/dev/null || true
  wait "$xvfb_pid" 2>/dev/null || true
fi
exit 1
