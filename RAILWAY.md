# Railway 部署（weather_v2）

## 从本仓库子目录部署

本机 Git 根目录是 **`20260407171347`**，应用代码在 **`weather_v2/`**。

1. 在 [railway.app](https://railway.app) 用 GitHub 登录 → **New Project** → **Deploy from GitHub repo** → 选该仓库。  
2. 打开服务 **Settings** → **Root Directory** 填 **`weather_v2`**（让 Railway 在子目录里找到 `Dockerfile`）。  
3. **Settings → Variables** 按下列名称添加变量（值见本地 `.env`，勿提交仓库）。  
4. 部署完成后用 Railway 提供的 **Public URL** 访问；平台会注入 **`PORT`**，镜像内已用 Gunicorn 绑定该端口。

## 建议环境变量

| 变量 | 说明 |
|------|------|
| `PORT` | 由 Railway 自动设置，一般无需手填 |
| `APP_SECRET_KEY` | 长随机串，如 `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_DEBUG` | 生产设 `false` |
| `USE_BI_DATA` | `true` 拉观远；无凭证可 `false` 走快照/空数据 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_BITABLE_APP_TOKEN` / `FEISHU_BITABLE_TABLE_ID` | 飞书（不用飞书可留空） |
| `GUANDATA_BASE_URL` | 观远站点根 URL |
| **`GUANDATA_APP_TOKEN` + `GUANDATA_LOGIN_ID`** | **推荐**：走 `/public-api/user/loginId/sign-in` 自动换取 `X-Auth-Token`，过期前写缓存并在接口返回认证错误时自动重登 |
| `GUANDATA_X_AUTH_TOKEN` | 仅临时调试；生产勿只靠此项（无法自动续期）。若必须只用粘贴 Token，设 `GUANDATA_ONLY_ENV_X_AUTH_TOKEN=true` |
| `GUANDATA_TOKEN_CACHE_PATH` / `GUANDATA_RUNTIME_DIR` | 可选；默认写到系统临时目录（容器内可写） |
| `GUANDATA_SOURCES_FILE` | 默认 `guandata_sources.json` |

更全说明见项目根下 **`weather_v2/.env.example`**。

## 仅部署「单目录应用」的替代做法

若希望 GitHub 仓库**根目录就是应用**（无 `weather_v2/` 这一层），可另建空仓库，只把 `weather_v2` 目录内容推成该仓库根目录，则 Railway 不必设 Root Directory。
