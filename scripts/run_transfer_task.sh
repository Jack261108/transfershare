#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

if [[ "${1:-}" == "--show-network-info" ]]; then
  echo "网络环境信息:"
  curl -s https://ipinfo.io/json || echo "无法获取IP信息"
  echo "========================================"
fi

python transfer_runner.py
