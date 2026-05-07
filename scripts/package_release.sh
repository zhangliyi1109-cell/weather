#!/usr/bin/env bash
# 在项目根目录 weather_v2 下生成发布包，便于上传到服务器解压部署。
# 用法: ./scripts/package_release.sh [版本后缀]
# 示例: ./scripts/package_release.sh 20260430

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(date +%Y%m%d_%H%M%S)}"
OUT="${ROOT}/weather_v2_release_${VERSION}.tar.gz"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"

echo "打包目录: ${ROOT}"
echo "输出文件: ${OUT}"

# 排除本地缓存、虚拟环境、历史压缩包与超大快照（需要时可单独拷贝到服务器）
tar -czf "${OUT}" \
  --exclude="${NAME}/.git" \
  --exclude="${NAME}/__pycache__" \
  --exclude="${NAME}/venv" \
  --exclude="${NAME}/.venv" \
  --exclude="${NAME}/*.tar.gz" \
  --exclude="${NAME}/bi_inventory_last_success.json" \
  -C "${PARENT}" "${NAME}"

echo "完成。上传到服务器后建议:"
echo "  python3 -m venv .venv && source .venv/bin/activate"
echo "  pip install -r requirements.txt -r requirements-prod.txt"
echo "  cp .env.example .env   # 填写 APP_SECRET_KEY 等"
echo "  export FLASK_DEBUG=false"
echo "  gunicorn -w 2 -b 0.0.0.0:5002 \"app:app\""
