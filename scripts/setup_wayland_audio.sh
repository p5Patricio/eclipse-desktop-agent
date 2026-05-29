#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[eclipse-setup] %s\n' "$1"
}

require_linux() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    printf 'This setup script only supports Linux.\n' >&2
    exit 1
  fi
}

require_fedora_tools() {
  if ! command -v dnf >/dev/null 2>&1; then
    printf 'This setup script targets Fedora and requires dnf.\n' >&2
    exit 1
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    printf 'sudo is required to install system packages and configure ydotoold.\n' >&2
    exit 1
  fi
}

install_packages() {
  log 'Installing Fedora audio and Wayland automation dependencies.'
  sudo dnf install -y portaudio-devel grim slurp ydotool
}

write_ydotool_service() {
  local socket_path="${ECLIPSE_YDOTOOL_SOCKET:-/run/ydotoold/eclipse.sock}"
  local uid
  local gid
  uid="$(id -u)"
  gid="$(id -g)"

  log "Configuring ydotoold with socket ${socket_path}."
  sudo tee /etc/systemd/system/eclipse-ydotoold.service >/dev/null <<SERVICE
[Unit]
Description=Eclipse ydotool daemon
Documentation=https://github.com/ReimuNotMoe/ydotool
After=multi-user.target

[Service]
Type=simple
RuntimeDirectory=ydotoold
ExecStart=/usr/bin/ydotoold --socket-path=${socket_path} --socket-own=${uid}:${gid} --socket-perm=0600
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
SERVICE

  sudo tee /etc/profile.d/eclipse-ydotool.sh >/dev/null <<PROFILE
# Eclipse desktop agent ydotool socket.
export YDOTOOL_SOCKET="${socket_path}"
PROFILE

  sudo systemctl daemon-reload
  sudo systemctl enable --now eclipse-ydotoold.service
}

show_next_steps() {
  log 'Setup complete.'
  printf '\nNext steps:\n'
  printf '  1. Open a new shell or run: source /etc/profile.d/eclipse-ydotool.sh\n'
  printf '  2. Test screenshot dry-run: PYTHONPATH=src python -m eclipse_agent fedora-screenshot\n'
  printf '  3. Test confirmed typing dry-run: PYTHONPATH=src python -m eclipse_agent fedora-type --text "hello" --confirmed\n'
  printf '  4. Use --execute only when you intentionally want Eclipse to touch the microphone or desktop.\n'
}

main() {
  require_linux
  require_fedora_tools
  install_packages
  write_ydotool_service
  show_next_steps
}

main "$@"
