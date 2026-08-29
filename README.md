# 卡密销售与提取系统

一个基于 FastAPI、SQLite 和 Vue 3 的卡密销售与账号提取系统。

管理员可以维护 sub2api 账号池、生成和管理卡密、查看提取记录；买家输入卡密后，可以获得账号导出压缩包。项目适合个人服务、小型团队或自托管场景。

## 功能

- 管理员登录、密码修改、会话管理和操作审计
- sub2api 分组、账号池、账号验活和提取状态管理
- 卡密生成、批次管理、筛选、禁用和删除
- 提取日志、趋势统计、库存预警和异常通知
- 买家卡密兑换，并下载包含 `sub2api.json` 和 `cpa.json` 的 ZIP
- sub2api JSON/JSONL 格式转换
- Cloudflare Turnstile 登录验证和渐进式买家验证
- Redis 跨进程限流、同一卡密互斥和全局兑换并发控制
- CSRF 双提交校验、可信主机校验、SSRF 主机白名单和安全响应头

## 工作方式

应用提供两个相互隔离的站点。生产环境建议为管理端和买家端使用不同的域名：

| 域名 | 用途 | 公开接口 |
| --- | --- | --- |
| `admin.example.com` | 管理后台 | 管理接口；拒绝 `/api/redeem` |
| `buyer.example.com` | 买家兑换页 | `/api/redeem`；拒绝 `/api/admin/*` |

请求会经过 FastAPI 的 Host 校验，Nginx 模板也会在边缘层重复执行站点隔离。不要把两个站点配置为同一个公开入口。

```text
浏览器
  ├─ admin.example.com  ─┐
  └─ buyer.example.com  ─┴─ Nginx ── FastAPI ── SQLite
                                      ├── Redis
                                      └── sub2api
```

敏感配置（sub2api 凭据、Turnstile 私钥和 SMTP 密码）由环境变量或后台设置提供，并使用 `APP_SECRET` 加密保存。数据库、密钥、证书和日志属于运行实例，不应提交到代码仓库。

## 技术栈

- Python 3.11+
- FastAPI、Uvicorn、HTTPX、cryptography、redis
- SQLite
- Vue 3、TypeScript、Pinia、Ant Design Vue、Vite
- Node.js 20+ 和 npm
- Nginx（生产环境）

## 项目结构

```text
backend/                 FastAPI、数据库、安全和兑换逻辑
frontend/admin.html      管理后台入口
frontend/buyer.html      买家兑换页入口
frontend/src/            Vue 页面、API 客户端和构建入口
frontend/public/         公共静态资源
frontend/.env.example    前端公开构建参数示例
deploy/                  环境变量、systemd 和 Nginx 模板
data/                    运行时数据库和应用密钥
tests/                   前端和后端测试
package.json             开发、构建、启动和测试命令
requirements.txt         Python 依赖
```

## 快速开始

### Windows PowerShell

```powershell
npm ci
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "replace-with-a-long-local-password"
$env:APP_SECRET = "replace-with-at-least-32-random-characters"
$env:COOKIE_SECURE = "0"
$env:ALLOWED_HOSTS = "admin.example.com,buyer.example.com,localhost,127.0.0.1"
$env:ADMIN_HOSTS = "admin.example.com"
$env:BUYER_HOSTS = "buyer.example.com"

npm start
```

另开一个终端启动 Vite 开发服务器：

```powershell
npm run dev
```

默认地址为 `http://127.0.0.1:5173`，Vite 会把 `/api` 请求代理到 `http://127.0.0.1:5230`。也可以直接运行后端并使用 `http://localhost:5230` 测试 API。

生产环境请显式设置 `ADMIN_PASSWORD` 和 `APP_SECRET`。未设置管理员密码时，首次启动会在 `data/admin-init.txt` 写入一次性初始口令。

## 配置

后端配置可以通过环境变量提供。部署时可复制 `deploy/key-sale-system.env.example`，再按实际环境修改。示例文件不包含可用凭据。

### 基础与站点

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_SECRET` | 自动生成 | 至少 32 个字符，用于加密敏感设置 |
| `ADMIN_USERNAME` | `admin` | 首次创建的管理员用户名 |
| `ADMIN_PASSWORD` | 空 | 首次创建管理员时使用的密码 |
| `COOKIE_SECURE` | `1` | HTTPS 生产环境保持为 `1` |
| `ENABLE_API_DOCS` | 关闭 | 是否开放 FastAPI 文档，生产环境建议关闭 |
| `DB_PATH` | `data/sale.sqlite` | SQLite 数据库路径 |
| `ALLOWED_HOSTS` | 示例域名和本机 | FastAPI 允许的 Host 列表 |
| `ADMIN_HOSTS` | `admin.example.com` | 管理站点 Host 列表 |
| `BUYER_HOSTS` | `buyer.example.com` | 买家站点 Host 列表 |
| `TRUSTED_PROXIES` | 空 | 允许转发客户端 IP 的代理地址 |

### sub2api 与 Turnstile

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SUB2API_BASE_URL` | `http://127.0.0.1:5220` | sub2api 服务地址 |
| `ALLOWED_SUB2API_HOSTS` | `127.0.0.1,localhost` | sub2api SSRF 主机白名单 |
| `SUB2API_API_KEY` | 空 | sub2api 管理 API 密钥 |
| `SUB2API_BEARER_TOKEN` | 空 | sub2api Bearer Token |
| `TURNSTILE_ENABLED` | 关闭 | 是否启用管理员登录 Turnstile |
| `TURNSTILE_SITE_KEY` | 空 | Turnstile 公开站点密钥 |
| `TURNSTILE_SECRET_KEY` | 空 | Turnstile 私密校验密钥 |

sub2api、Turnstile、SMTP 和库存预警也可以在管理后台设置页配置。敏感字段只显示配置状态，不会通过 API 回显明文。

### 登录与兑换防护

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOGIN_LOCK_ATTEMPTS` | `5` | 同一 IP 和用户名触发锁定的失败次数 |
| `LOGIN_LOCK_SECONDS` | `900` | 登录锁定时长（秒） |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 跨进程限流与并发控制使用的 Redis |
| `REDEEM_MAX_BODY_BYTES` | `2048` | `/api/redeem` 请求体上限 |
| `REDEEM_IP_LIMIT` / `REDEEM_IP_WINDOW_SECONDS` | `20` / `60` | 单 IP 兑换次数和窗口 |
| `REDEEM_CARD_LIMIT` / `REDEEM_CARD_WINDOW_SECONDS` | `5` / `300` | 单卡密尝试次数和窗口 |
| `REDEEM_FAILURE_THRESHOLD` / `REDEEM_FAILURE_WINDOW_SECONDS` | `5` / `600` | 触发买家 Turnstile 的失败阈值和窗口 |
| `REDEEM_CONCURRENCY` | `10` | 全服务器同时执行的兑换任务上限 |
| `REDEEM_PREPARE_TIMEOUT_SECONDS` | `180` | 单次兑换准备和验活流程总超时 |
| `REDEEM_LEASE_SECONDS` | `210` | Redis 任务租约，必须大于总超时 |

### 前端公开变量

前端构建时可以通过 `frontend/.env.example` 中的变量设置公开链接：

```dotenv
VITE_CARD_REDEEM_URL=https://buyer.example.com/
VITE_FORMAT_CONVERTER_URL=https://converter.example.com/
```

`VITE_*` 变量会进入浏览器代码，只能填写公开 URL，不能填写密钥或 Token。

## 生产部署

项目提供通用的 systemd 和 Nginx 模板，部署到 Linux 服务器时按以下步骤操作：

1. 安装 Python 3.11+、Node.js 20+、Redis、Nginx，并准备可用的 sub2api 服务。
2. 将源码放到服务器应用目录，复制 `deploy/key-sale-system.env.example` 为服务器专用环境文件，填写域名、密码、`APP_SECRET`、Redis 和 sub2api 配置。
3. 安装依赖并在服务器上构建前端：

   ```bash
   npm ci
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   npm run build
   ```

4. 根据应用目录、运行用户和环境文件位置修改 `deploy/key-sale-system.service`，再安装 systemd 单元。
5. 复制并修改以下 Nginx 模板中的域名、证书、日志和 ACME 路径：

   - `deploy/admin.example.com.secure.conf`
   - `deploy/buyer.example.com.secure.conf`
   - `deploy/default-deny.conf`
   - `deploy/redeem-rate-limit.conf`

   将限流配置作为 Nginx `http` 级 include，面板环境可命名为 `0.redeem-rate-limit.conf`。默认拒绝模板可命名为 `0.default.conf`，确保默认拒绝站点优先加载并位于其他站点配置之前。确认 `nginx -t` 通过后再重新加载 Nginx。
6. 启动应用并确认服务状态：

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now key-sale-system.service
   sudo systemctl status key-sale-system.service
   ```

管理域名和买家域名必须分别配置 HTTPS。Redis 应仅监听本机或可信内网，应用的 `data/` 目录、环境文件、证书和日志目录应限制为服务器账户可读。

## 安全特性

- 仅允许 TLS 1.2/1.3，并使用具备前向保密的 ECDHE + AEAD 密码套件。
- 管理端与买家端按 Host 和 Nginx 路由隔离，未知 Host 会被拒绝。
- `/api/redeem` 使用 Redis 进行 IP/卡密限流、同卡互斥、全局并发限制和总超时控制。
- 管理员登录支持持久化失败锁定；买家只有连续失败达到阈值后才需要 Turnstile。
- 管理写请求启用同源校验和 CSRF 双提交 Token，会话 Token 只以哈希形式保存。
- sub2api 请求受主机白名单约束，避免把应用滥用为内网探测器。
- 默认关闭 FastAPI 文档，并发送 HSTS、CSP、COOP、CORP 等安全响应头。

安全问题请按照 `SECURITY.md` 的私密报告流程提交，不要在公开 issue 中发布凭据、卡密、数据库或用户数据。

## 开发与测试

```bash
npm test
npm run build
```

`npm test` 会运行前端 Node.js 测试和后端 Python 测试；`npm run build` 会分别构建管理端和买家端，产物写入 `frontend/dist/`。

提交改动前请阅读 `CONTRIBUTING.md`，并确保新增配置同步更新示例文件和文档。

## 许可证

本项目采用 MIT License，详见 `LICENSE`。
