#!/usr/bin/env bash
# Render the working config from environment (.env), then run the capturer.
set -euo pipefail

TEMPLATE="/app/config/config.yaml.template"
RENDERED="/run/skycam/config.yaml"

# Required — no sensible default; fail loudly if unset or empty.
: "${TAPO_USERNAME:?must be set (see .env.example)}"
: "${TAPO_PASSWORD:?must be set (see .env.example)}"
: "${CAMERA_IP:?must be set (see .env.example)}"
: "${LATITUDE:?must be set (see .env.example)}"
: "${LONGITUDE:?must be set (see .env.example)}"

# Optional — apply defaults so a minimal .env still works.
: "${CAMERA_PORT:=554}"
: "${CAMERA_STREAM:=stream1}"
: "${ELEVATION:=0}"
: "${SUN_LIMIT:=-8.0}"
: "${INTERVAL:=15}"
: "${CAM_LABEL:=skycam}"
export CAMERA_PORT CAMERA_STREAM ELEVATION SUN_LIMIT INTERVAL CAM_LABEL

mkdir -p "$(dirname "$RENDERED")"

# Only substitute our known variables (never touch other $-tokens).
envsubst '${TAPO_USERNAME} ${TAPO_PASSWORD} ${CAMERA_IP} ${CAMERA_PORT} ${CAMERA_STREAM} ${LATITUDE} ${LONGITUDE} ${ELEVATION} ${SUN_LIMIT} ${INTERVAL} ${CAM_LABEL}' \
    < "$TEMPLATE" > "$RENDERED"

echo "[entrypoint] rendered $RENDERED (label=$CAM_LABEL interval=${INTERVAL}s stream=$CAMERA_STREAM sun_limit=$SUN_LIMIT)"
exec python /app/src/capture.py "$RENDERED"
