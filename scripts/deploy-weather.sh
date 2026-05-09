#!/bin/bash
# 在云服务器上部署本仓库（Ubuntu/Debian 示例）。
# 用法：复制到服务器后 chmod +x deploy-weather.sh && sudo ./deploy-weather.sh
# 或使用文档中的 heredoc 写入 /tmp/deploy-weather.sh 再执行。

set -e

GITHUB_REPO="${GITHUB_REPO:-https://github.com/zhangliyi1109-cell/weather.git}"
APP_DIR="${APP_DIR:-/data/weather}"
APP_NAME="${APP_NAME:-weather}"
PORT="${PORT:-5000}"

echo "===== Weather 服务部署脚本 ====="
echo "APP_DIR=$APP_DIR  PORT=$PORT"

# 1. 系统依赖
echo "[1/6] 安装系统依赖..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git ca-certificates

# 2. 拉取代码（支持重复执行：已存在则 pull）
echo "[2/6] 拉取代码..."
mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all
  git -C "$APP_DIR" pull --ff-only origin main || git -C "$APP_DIR" pull --ff-only origin master
else
  git clone "$GITHUB_REPO" "$APP_DIR"
fi

# 3. Python 虚拟环境 + 依赖（避免污染系统 Python，兼容 Ubuntu 24+）
echo "[3/6] 安装 Python 依赖..."
python3 -m venv "$APP_DIR/.venv"
# shellcheck source=/dev/null
source "$APP_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

# 4. PM2（需已安装 Node；若无请先: apt install -y nodejs npm 或使用 nvm）
echo "[4/6] 安装 PM2..."
if ! command -v npm >/dev/null 2>&1; then
  echo "未检测到 npm，正在尝试安装 nodejs/npm..."
  apt-get install -y nodejs npm
fi
npm install -g pm2

# 5. 用 PM2 启动（端口写入 ecosystem，确保子进程能读到 PORT / SERVER_PORT）
echo "[5/6] 启动服务..."
pm2 delete "$APP_NAME" 2>/dev/null || true
SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
FLASK_DEBUG="${FLASK_DEBUG:-false}"
cat > "$APP_DIR/ecosystem.config.cjs" << EOF
module.exports = {
  apps: [{
    name: "${APP_NAME}",
    script: "app.py",
    interpreter: "${APP_DIR}/.venv/bin/python",
    cwd: "${APP_DIR}",
    env: {
      PORT: "${PORT}",
      SERVER_PORT: "${PORT}",
      SERVER_HOST: "${SERVER_HOST}",
      FLASK_DEBUG: "${FLASK_DEBUG}",
    },
  }],
};
EOF
cd "$APP_DIR"
pm2 start ecosystem.config.cjs
pm2 save

# 6. 开机自启（通常会打印一行需手动执行的 sudo 命令，请留意终端输出）
echo "[6/6] 配置开机自启（请根据 pm2 提示执行 sudo 那条命令）..."
pm2 startup systemd -u "${SUDO_USER:-$USER}" --hp "${HOME:-/root}" || pm2 startup || true

echo ""
echo "===== 部署完成 ====="
echo "监听端口以环境变量为准：PORT=$PORT（与 Flask config 中 SERVER_PORT 一致）"
echo "若本机防火墙/安全组放行，可访问: http://<服务器公网IP>:$PORT"
echo ""
echo "请在 $APP_DIR 手动创建 .env（勿提交仓库），填写观远/飞书等密钥。"
echo "登录账号：复制 app_users.example.json 为 app_users.json 并改密码，或在环境变量设置 APP_USERS_JSON。"
echo ""
echo "常用命令:"
echo "  pm2 logs $APP_NAME       # 查看日志"
echo "  pm2 restart $APP_NAME   # 重启"
echo "  pm2 stop $APP_NAME      # 停止"
