#!/usr/bin/env bash
set -Eeuo pipefail

TEXT_MODEL_NAME="${ECLIPSE_LOCAL_LLM_MODEL:-qwen2.5:7b}"
VISION_MODEL_NAME="${ECLIPSE_LOCAL_VISION_MODEL:-qwen2.5vl:7b}"
OLLAMA_HOST_VALUE="${OLLAMA_HOST:-127.0.0.1:11434}"
OLLAMA_INSTALL_URL="https://ollama.com/install.sh"

log() {
  printf '[eclipse-local-llm] %s\n' "$*"
}

require_linux() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    log "This setup script supports Linux only."
    exit 1
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    log "Missing required command: ${command_name}"
    exit 1
  fi
}

install_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    log "Ollama is already installed: $(command -v ollama)"
    return
  fi

  require_command curl
  log "Installing Ollama from ${OLLAMA_INSTALL_URL}"
  curl -fsSL "${OLLAMA_INSTALL_URL}" | sh
}

configure_systemd_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    log "systemctl is not available; skipping service enablement."
    return
  fi

  local ollama_bin
  ollama_bin="$(command -v ollama)"

  if ! id ollama >/dev/null 2>&1; then
    log "Creating system user: ollama"
    sudo useradd --system --home /usr/share/ollama --shell /usr/sbin/nologin ollama
  fi

  for group_name in render video; do
    if getent group "${group_name}" >/dev/null 2>&1; then
      sudo usermod -a -G "${group_name}" ollama || true
    fi
  done

  if ! systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    log "Creating /etc/systemd/system/ollama.service"
    sudo tee /etc/systemd/system/ollama.service >/dev/null <<EOF
[Unit]
Description=Ollama local model server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${ollama_bin} serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment=OLLAMA_HOST=${OLLAMA_HOST_VALUE}
Environment=OLLAMA_MODELS=/usr/share/ollama/.ollama/models

[Install]
WantedBy=multi-user.target
EOF
  fi

  log "Enabling and starting ollama.service"
  sudo systemctl daemon-reload
  sudo systemctl enable --now ollama.service
}

wait_for_ollama() {
  require_command curl
  local base_url="http://${OLLAMA_HOST_VALUE}"
  log "Waiting for Ollama at ${base_url}"
  for _ in $(seq 1 30); do
    if curl -fsS "${base_url}/api/tags" >/dev/null 2>&1; then
      log "Ollama is ready."
      return
    fi
    sleep 1
  done
  log "Ollama did not become ready within 30 seconds."
  exit 1
}

pull_models() {
  log "Pulling local planning model: ${TEXT_MODEL_NAME}"
  ollama pull "${TEXT_MODEL_NAME}"
  log "Pulling local vision model for dynamic screenshot routing: ${VISION_MODEL_NAME}"
  ollama pull "${VISION_MODEL_NAME}"
}

main() {
  require_linux
  install_ollama
  configure_systemd_service
  wait_for_ollama
  pull_models
  log "Local LLM setup complete."
  log "Eclipse can use http://${OLLAMA_HOST_VALUE}/v1 with text model ${TEXT_MODEL_NAME}."
  log "Eclipse can use vision model ${VISION_MODEL_NAME} for screenshot analysis."
}

main "$@"
