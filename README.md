# cert_auto_api

[中文](#中文说明) | [English](#english)

Automatic certificate issuance and renewal API built with Python. It prefers `acme.sh` when available and falls back to a built-in Cloudflare API Token ACME engine, with a client sync script for pulling updated certificates and restarting `XrayR`.

一个基于 Python 的自动证书签发与续签 API。优先使用 `acme.sh`，若不存在则回退到项目内置的 Cloudflare API Token ACME 引擎，并提供客户端同步脚本用于拉取最新证书并重启 `XrayR`。

## 中文说明

### 项目简介

`cert_auto_api` 用于在服务端统一管理泛域名证书的签发、续签和分发。

它支持：

- 自动检测宝塔或自安装 `acme.sh`
- 当 `acme.sh` 不可用时，自动切换到内置 Python ACME 引擎
- 通过 Cloudflare DNS API 签发主域名与泛域名证书
- 仅在证书剩余有效期小于等于 15 天时执行续签
- 通过 API 提供证书到期时间查询和证书下载
- 通过客户端脚本自动同步新证书到业务服务器并重启 `xrayr`

### 功能特性

- 基于 `.env` 进行配置
- 支持 `fullchain` 导出
- 支持 `certificate.cert` 与 `private.key` 标准文件输出
- 支持服务端定时自动检测续签
- 支持客户端按需拉取，避免重复下载和重复重启
- 支持 Bearer Token 或 `X-API-Token` 方式鉴权

### 目录结构

```text
cert_auto_api/
├── cert_auto_api/                # Python 服务端代码
├── client/                       # 客户端同步脚本
├── scripts/                      # 服务端辅助脚本
├── .env.example                  # 环境变量示例
├── CHANGELOG.md
├── requirements.txt              # Python 依赖
├── LICENSE
└── README.md
```

### 工作流程

1. 服务端读取 `.env` 配置。
2. 服务端优先寻找可用的 `acme.sh`，找不到时回退到内置 Python ACME 引擎。
3. 使用 Cloudflare DNS 验证签发主域名和泛域名证书。
   相关准备说明见 [docs/cloudflare_wildcard_dns_setup.md](/mnt/f/workwww/cert_auto_api/docs/cloudflare_wildcard_dns_setup.md)。
4. 证书保存为 `certificate.cert`，私钥保存为 `private.key`。
5. 服务端通过定时任务每天检查一次证书有效期。
6. 当证书剩余有效期小于等于 15 天时自动续签。
7. 客户端定时访问 API，对比远端证书时间和指纹。
8. 若远端证书已更新，则下载、解压并重启 `xrayr`。

双保险机制：

- API 启动时会自动检查并补装服务端续签 `cron`
- 客户端访问证书相关 API 时，服务端也会再次检查 `cron` 是否存在
- 如果 `cron` 被误删，服务端会在下次启动或下次接口访问时自动补上
- 服务端 `cron` 每天检查证书到期时间
- 客户端访问证书相关接口时，服务端也会再次检查证书
- 如果证书目录为空，或证书剩余有效期小于等于 15 天，会在后台触发续签
- 接口不会等待续签完成，客户端下次轮询到新证书后再下载即可

### 环境要求

- Linux
- Python 3.10+
- `acme.sh` 可选，若不存在则由项目内置引擎接管
- Cloudflare Token
- `curl`
- `tar`
- `openssl`

### 安装

```bash
cd /path/to/cert_auto_api
python3 -m pip install -r requirements.txt
cp .env.example .env
```

如果系统支持虚拟环境，也可以使用：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置说明

编辑 `.env`：

```env
API_HOST=0.0.0.0
API_PORT=8080
API_TOKEN=replace_with_32_char_token
API_PREFIX=/api/v1

CERT_DOMAINS=example.com,*.example.com
CF_TOKEN=replace_with_cloudflare_token
CERT_OUTPUT_DIR=./certs
RENEW_THRESHOLD_DAYS=15

ACME_DNS_PROVIDER=dns_cf
ACME_KEYLENGTH=ec-256
ACME_CONTACT_EMAIL=
ACME_DIRECTORY_URL=https://acme-v02.api.letsencrypt.org/directory
DNS_PROPAGATION_TIMEOUT=180
DNS_POLL_INTERVAL=10
```

关键字段：

- `CERT_DOMAINS`：证书域名列表，逗号分隔
- `CF_TOKEN`：Cloudflare DNS API Token
- `API_TOKEN`：访问 API 所需的鉴权 Token
- `CERT_OUTPUT_DIR`：证书输出目录
- `RENEW_THRESHOLD_DAYS`：提前多少天触发续签
- `ACME_CONTACT_EMAIL`：可选，作为 ACME 账号联系邮箱
- `ACME_DIRECTORY_URL`：可选，默认使用 Let's Encrypt 正式环境
- `DNS_PROPAGATION_TIMEOUT` / `DNS_POLL_INTERVAL`：内置引擎等待 DNS 生效的超时和轮询间隔

说明：

- 主域名不再单独配置
- 程序会自动从 `CERT_DOMAINS` 中选择第一个非通配符域名作为主域名
- 例如 `CERT_DOMAINS=example.com,*.example.com` 时，主域名会自动识别为 `example.com`
- `acme.sh` 路径不再单独配置，程序会自动识别
- 服务端部署和配置示例见 [docs/server_api_deployment.md](/mnt/f/workwww/cert_auto_api/docs/server_api_deployment.md)
- 已知问题与后续迭代见 [docs/known_issues_and_future_work.md](/mnt/f/workwww/cert_auto_api/docs/known_issues_and_future_work.md)
- 本次变更记录见 [CHANGELOG.md](/mnt/f/workwww/cert_auto_api/CHANGELOG.md)

证书引擎说明：

- 只要检测到可用的 `acme.sh`，优先使用 `acme.sh`
- 如果没有可用的 `acme.sh`，则回退到项目内置的 Python ACME 引擎
- 内置引擎直接使用 Cloudflare API Token 创建 `_acme-challenge` TXT 记录，并把 `fullchain` 和私钥写入 `CERT_OUTPUT_DIR`
- 宝塔 `acme_v2.py` 不再参与主流程

默认会自动尝试以下路径：

- `/www/server/panel/.acme.sh/acme.sh`
- `/root/.acme.sh/acme.sh`
- `~/.acme.sh/acme.sh`

### 启动服务端 API

```bash
python3 main.py serve
```

等价命令：

```bash
python3 -m cert_auto_api.cli serve
```

健康检查：

```bash
curl http://127.0.0.1:8080/healthz
```

### API 接口

默认前缀：`/api/v1`

认证方式：

- `Authorization: Bearer <API_TOKEN>`
- `X-API-Token: <API_TOKEN>`

接口列表：

- `GET /healthz`
- `GET /api/v1/certificate/info`
- `POST /api/v1/certificate/check-renew`
- `GET /api/v1/certificate/download`

查询证书信息：

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/info
```

返回字段中包含：

- `renewal_running`：当前是否有后台续签任务正在执行
- `renewal_status`：服务端记录的续签状态，包含 `idle`、`running`、`success`、`failed`
- `renewal_log_file`：服务端后台续签日志文件路径
- `engine`：当前实际使用的证书引擎，可能是 `acme_sh` 或 `builtin_acme`

手动触发检查续签：

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/check-renew
```

这个接口只负责触发后台续签检查，不会等待续签完成。

后台续签日志默认写入：

```text
CERT_OUTPUT_DIR/.renew.log
```

内置引擎状态目录与状态文件：

- `CERT_OUTPUT_DIR/.engine_state/`：内置 ACME 引擎的账号状态目录
- `CERT_OUTPUT_DIR/.renew.log`：后台续签日志
- `CERT_OUTPUT_DIR/.renew_status.json`：最近一次续签状态快照

下载证书压缩包：

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/download \
  -o certificate_bundle.tgz
```

如果证书缺失或后台续签尚未完成，接口会返回 `409`，客户端应等待下次轮询再试。

压缩包内容：

- `certificate.cert`
- `private.key`

其中 `certificate.cert` 为 `fullchain` 文件。

### 服务端定时续签

手动执行：

```bash
python3 main.py check-renew
```

直接执行续签脚本：

```bash
/bin/bash /path/to/cert_auto_api/scripts/server_cron.sh
```

自动安装服务端定时任务：

```bash
chmod 700 /path/to/cert_auto_api/scripts/install_server_cron.sh
/bin/bash /path/to/cert_auto_api/scripts/install_server_cron.sh
```

该安装脚本会：

- 检查当前用户 `crontab`
- 如果不存在续签任务，则自动写入
- 如果已存在相同任务，则不重复写入
- 固定每天 `03:00` 运行

当前默认行为：

- API 启动时会自动尝试执行一次该安装脚本
- `certificate/info`、`certificate/check-renew`、`certificate/download` 接口被访问时，也会再次检查并补装
- `certificate/info`、`certificate/check-renew` 和 `certificate/download` 接口被访问时，也会检查证书状态
- 如果证书缺失，或证书到期时间小于等于 15 天，服务端会后台触发一次续签任务
- 接口本身不会阻塞等待续签完成，避免客户端轮询时占用过多服务端资源
- 如果 `certificate/download` 被请求时证书仍不存在或仍在续签中，接口会返回 `409`
- 后台续签的标准输出和错误输出会写入 `CERT_OUTPUT_DIR/.renew.log`
- 如果系统缺少 `crontab` 或当前用户无权限写入 `crontab`，API 不会中断，但服务端日志会记录告警

实际写入内容：

```cron
0 3 * * * /bin/bash /path/to/cert_auto_api/scripts/server_cron.sh >> /var/log/cert_auto_api.log 2>&1
```

### 客户端自动同步

客户端脚本：`client/sync_cert.sh`

客户端 `cron` 安装脚本：`client/install_client_cron.sh`

赋予执行权限：

```bash
chmod 700 /path/to/cert_auto_api/client/sync_cert.sh
```

执行示例：

```bash
API_BASE_URL="https://your-api-host/api/v1" \
API_TOKEN="your_api_token" \
CERT_DEST_DIR="/etc/XrayR/cert" \
XRAYR_SERVICE_NAME="xrayr" \
/path/to/cert_auto_api/client/sync_cert.sh
```

自动安装客户端定时任务：

```bash
chmod 700 /path/to/cert_auto_api/client/install_client_cron.sh
API_BASE_URL="https://your-api-host/api/v1" \
API_TOKEN="your_api_token" \
CERT_DEST_DIR="/etc/XrayR/cert" \
XRAYR_SERVICE_NAME="XrayR" \
/bin/bash /path/to/cert_auto_api/client/install_client_cron.sh
```

客户端会：

- 查询服务端证书到期时间和证书指纹
- 对比本地证书信息
- 仅在远端证书更新时才下载
- 下载后解压覆盖目标目录
- 完成后重启 `xrayr`

客户端 `cron` 说明：

- 安装脚本会为每台客户端随机选择一个固定时间
- 随机范围是每天 `03:00-05:59`
- 这样可以避免大量客户端在同一时间集中请求服务端
- 随机时间会持久化到 `client/.client_sync_schedule`
- 重新执行安装脚本时，会复用原有时间，不会重新随机
- 如果客户端 `cron` 已存在，则不会重复添加

### 安全说明

- 请使用强随机 `API_TOKEN`
- 建议将 API 放在 HTTPS 或反向代理之后
- `CF_TOKEN` 只授予必要的 DNS 权限
- 私钥文件应保持最小权限访问
- 服务端 API 默认建议使用 `root` 运行
- 如果必须使用 `www` 等低权限用户，请自行确认其具备 `acme.sh` 执行、`crontab` 写入、证书目录写入和服务管理权限
- 客户端脚本建议由具备写权限和服务重启权限的用户执行

## English

### Overview

`cert_auto_api` is a Python-based certificate issuance, renewal, and distribution service for wildcard certificates. It prefers `acme.sh` and falls back to a built-in Cloudflare API Token ACME engine when `acme.sh` is unavailable.

It supports:

- BaoTa-installed `acme.sh`
- Self-installed `acme.sh`
- Built-in Python ACME fallback for Cloudflare API Token workflows
- Cloudflare DNS validation
- Automatic renewal for certificates expiring within 15 days
- API-based certificate status query and download
- Client-side synchronization with automatic `xrayr` restart

### Features

- Environment-based configuration via `.env`
- Fullchain export support
- Standard output files: `certificate.cert` and `private.key`
- Server-side scheduled renewal checks
- Client-side pull-based synchronization
- Token-based API authentication

### Project Structure

```text
cert_auto_api/
├── cert_auto_api/                # Python server code
├── client/                       # Client sync script
├── scripts/                      # Server helper scripts
├── .env.example                  # Example environment variables
├── CHANGELOG.md
├── requirements.txt              # Python dependencies
├── LICENSE
└── README.md
```

### Workflow

1. The server loads configuration from `.env`.
2. The server prefers an available `acme.sh` installation and falls back to the built-in Python ACME engine when `acme.sh` is unavailable.
3. Certificates are issued or renewed through Cloudflare DNS validation.
   See [docs/cloudflare_wildcard_dns_setup.md](/mnt/f/workwww/cert_auto_api/docs/cloudflare_wildcard_dns_setup.md) for Cloudflare DNS preparation steps.
4. The fullchain is saved as `certificate.cert`, and the private key as `private.key`.
5. A scheduled task checks certificate expiration once per day.
6. Certificates are renewed only when the remaining lifetime is 15 days or less.
7. The client polls the API for expiration time and certificate fingerprint.
8. The client downloads and extracts the new certificate only when an update is detected.

Defense in depth:

- the API automatically checks and installs the renewal cron job on startup
- certificate-related API requests also re-check the cron entry
- if the cron entry is deleted accidentally, it is restored on the next startup or API request
- the server cron checks certificate expiration every day
- certificate-related API requests also re-check the certificate state
- if the certificate is missing or expires within 15 days, the server triggers a background renewal
- the API does not wait for renewal to finish, so client polling stays lightweight

### Requirements

- Linux
- Python 3.10+
- `acme.sh` is optional; the built-in engine takes over when it is unavailable
- Cloudflare API Token
- `curl`
- `tar`
- `openssl`

### Installation

```bash
cd /path/to/cert_auto_api
python3 -m pip install -r requirements.txt
cp .env.example .env
```

If your environment supports virtual environments:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Edit `.env`:

```env
API_HOST=0.0.0.0
API_PORT=8080
API_TOKEN=replace_with_32_char_token
API_PREFIX=/api/v1

CERT_DOMAINS=example.com,*.example.com
CF_TOKEN=replace_with_cloudflare_token
CERT_OUTPUT_DIR=./certs
RENEW_THRESHOLD_DAYS=15

ACME_DNS_PROVIDER=dns_cf
ACME_KEYLENGTH=ec-256
ACME_CONTACT_EMAIL=
ACME_DIRECTORY_URL=https://acme-v02.api.letsencrypt.org/directory
DNS_PROPAGATION_TIMEOUT=180
DNS_POLL_INTERVAL=10
```

Important fields:

- `CERT_DOMAINS`: comma-separated certificate domains
- `CF_TOKEN`: Cloudflare DNS API token
- `API_TOKEN`: token required to access the API
- `CERT_OUTPUT_DIR`: certificate output directory
- `RENEW_THRESHOLD_DAYS`: renewal threshold in days
- `ACME_CONTACT_EMAIL`: optional contact email for the ACME account
- `ACME_DIRECTORY_URL`: optional ACME directory URL, defaults to Let's Encrypt production
- `DNS_PROPAGATION_TIMEOUT` / `DNS_POLL_INTERVAL`: built-in engine DNS propagation wait controls

Notes:

- The primary domain is no longer configured separately.
- The program automatically selects the first non-wildcard entry in `CERT_DOMAINS` as the primary domain.
- For example, with `CERT_DOMAINS=example.com,*.example.com`, the primary domain is `example.com`.
- `acme.sh` is detected automatically and no longer configured manually.
- Server-side deployment examples are documented in [docs/server_api_deployment.md](/mnt/f/workwww/cert_auto_api/docs/server_api_deployment.md).
- Known issues and future work are documented in [docs/known_issues_and_future_work.md](/mnt/f/workwww/cert_auto_api/docs/known_issues_and_future_work.md).
- This round of changes is recorded in [CHANGELOG.md](/mnt/f/workwww/cert_auto_api/CHANGELOG.md).

Certificate engine notes:

- if `acme.sh` is available, the project uses `acme.sh`
- if `acme.sh` is unavailable, the project falls back to the built-in Python ACME engine
- the built-in engine uses the Cloudflare API Token flow to create `_acme-challenge` TXT records and writes the resulting `fullchain` and private key into `CERT_OUTPUT_DIR`
- BaoTa `acme_v2.py` is no longer part of the main issuance path

The server automatically checks these common paths:

- `/www/server/panel/.acme.sh/acme.sh`
- `/root/.acme.sh/acme.sh`
- `~/.acme.sh/acme.sh`

### Start the API Server

```bash
python3 main.py serve
```

Equivalent command:

```bash
python3 -m cert_auto_api.cli serve
```

Health check:

```bash
curl http://127.0.0.1:8080/healthz
```

### API Endpoints

Default prefix: `/api/v1`

Authentication:

- `Authorization: Bearer <API_TOKEN>`
- `X-API-Token: <API_TOKEN>`

Available endpoints:

- `GET /healthz`
- `GET /api/v1/certificate/info`
- `POST /api/v1/certificate/check-renew`
- `GET /api/v1/certificate/download`

Get certificate info:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/info
```

The response includes:

- `renewal_running`: whether a background renewal task is currently running
- `renewal_status`: server-side renewal state, including `idle`, `running`, `success`, and `failed`
- `renewal_log_file`: path to the server-side background renewal log file
- `engine`: the active certificate engine, either `acme_sh` or `builtin_acme`

Trigger a renewal check:

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/check-renew
```

This endpoint triggers a background renewal check and returns immediately.

Background renewal logs are written to:

```text
CERT_OUTPUT_DIR/.renew.log
```

Built-in engine state and status files:

- `CERT_OUTPUT_DIR/.engine_state/`: built-in ACME engine account state
- `CERT_OUTPUT_DIR/.renew.log`: background renewal log
- `CERT_OUTPUT_DIR/.renew_status.json`: last renewal status snapshot

Download the certificate bundle:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:8080/api/v1/certificate/download \
  -o certificate_bundle.tgz
```

If the certificate is missing or the background renewal has not finished yet, the endpoint returns `409` and the client should retry later.

Bundle contents:

- `certificate.cert`
- `private.key`

`certificate.cert` is the fullchain file.

### Server-side Scheduled Renewal

Run once manually:

```bash
python3 main.py check-renew
```

Run the renewal script directly:

```bash
/bin/bash /path/to/cert_auto_api/scripts/server_cron.sh
```

Install the server cron job automatically:

```bash
chmod 700 /path/to/cert_auto_api/scripts/install_server_cron.sh
/bin/bash /path/to/cert_auto_api/scripts/install_server_cron.sh
```

The installer script:

- checks the current user crontab
- adds the renewal task only if it does not already exist
- skips changes if the exact task is already present
- schedules it for `03:00` every day

Default behavior:

- the API automatically attempts to run this installer during startup
- the `certificate/info`, `certificate/check-renew`, and `certificate/download` endpoints also re-check and restore the cron job when needed
- the `certificate/info`, `certificate/check-renew`, and `certificate/download` endpoints also check certificate status
- if the certificate is missing or expires in 15 days or less, the server starts a background renewal task
- the API does not block waiting for renewal to finish, which avoids wasting server resources when many clients are polling
- `certificate/download` returns `409` if the certificate is still missing or renewal is still in progress
- background renewal stdout and stderr are written to `CERT_OUTPUT_DIR/.renew.log`
- if `crontab` is unavailable or the current user cannot modify it, the API keeps running and logs a warning instead of failing hard

Installed cron line:

```cron
0 3 * * * /bin/bash /path/to/cert_auto_api/scripts/server_cron.sh >> /var/log/cert_auto_api.log 2>&1
```

### Client-side Synchronization

Client script: `client/sync_cert.sh`

Client cron installer: `client/install_client_cron.sh`

Make it executable:

```bash
chmod 700 /path/to/cert_auto_api/client/sync_cert.sh
```

Example:

```bash
API_BASE_URL="https://your-api-host/api/v1" \
API_TOKEN="your_api_token" \
CERT_DEST_DIR="/etc/XrayR/cert" \
XRAYR_SERVICE_NAME="xrayr" \
/path/to/cert_auto_api/client/sync_cert.sh
```

Install the client cron job automatically:

```bash
chmod 700 /path/to/cert_auto_api/client/install_client_cron.sh
API_BASE_URL="https://your-api-host/api/v1" \
API_TOKEN="your_api_token" \
CERT_DEST_DIR="/etc/XrayR/cert" \
XRAYR_SERVICE_NAME="XrayR" \
/bin/bash /path/to/cert_auto_api/client/install_client_cron.sh
```

The client script:

- fetches remote certificate expiration time and fingerprint
- compares them with the local certificate
- downloads only when the remote certificate has changed
- extracts the bundle into the target directory
- restarts `xrayr` after update

Client cron behavior:

- the installer picks one fixed random time for each client
- the random window is `03:00-05:59` every day
- this spreads requests across many clients and avoids synchronized load spikes
- the selected time is persisted in `client/.client_sync_schedule`
- rerunning the installer reuses the same time instead of generating a new one
- if the client cron already exists, the installer does nothing

### Security Notes

- Use a strong random `API_TOKEN`
- Put the API behind HTTPS or a reverse proxy in production
- Grant only the minimum required DNS permissions to `CF_TOKEN`
- Keep private key permissions restricted
- Running the server API as `root` is the default recommendation
- If you run it as a lower-privileged user such as `www`, make sure it can execute `acme.sh`, write `crontab`, write the certificate directory, and manage required services
- Run the client script with a user that can write cert files and restart services

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
