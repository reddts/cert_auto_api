# 服务端 API 配置说明

本文档说明如何在两种常见环境中部署和配置 `cert_auto_api` 服务端：

- 宝塔环境
- 独立 Linux 环境

适用目标：

- 运行服务端 API
- 自动识别并调用可用的 `acme.sh`
- 使用 Cloudflare DNS API 自动签发和续签证书

## 一、通用要求

无论是宝塔还是独立部署，都需要满足：

- Linux 系统
- Python 3.10+
- 已安装 `acme.sh`
- 已接入 Cloudflare DNS
- 已准备好 `CF_TOKEN`

项目关键配置位于 `.env`：

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
```

说明：

- `CERT_DOMAINS` 填写主域名和泛域名
- `CF_TOKEN` 为 Cloudflare API Token
- `CERT_OUTPUT_DIR` 为服务端 fullchain 和私钥输出目录
- `RENEW_THRESHOLD_DAYS` 一般保持 `15`

## 二、宝塔环境配置

### 1. 适用情况

适用于：

- 服务器已安装宝塔面板
- `acme.sh` 由宝塔自动安装

本项目默认优先检测宝塔 `acme.sh` 路径：

```text
/www/server/panel/.acme.sh/acme.sh
```

因此在宝塔环境中，一般不需要额外指定路径。

### 2. 建议部署目录

建议将项目放在一个固定目录，例如：

```bash
/opt/cert_auto_api
```

或：

```bash
/www/wwwroot/cert_auto_api
```

只要确保运行 API 的用户有以下权限即可：

- 可读取项目目录
- 可写入 `CERT_OUTPUT_DIR`
- 可执行宝塔的 `acme.sh`
- 可写入当前用户的 `crontab`

### 3. 安装依赖

```bash
cd /path/to/cert_auto_api
python3 -m pip install -r requirements.txt
cp .env.example .env
```

### 4. 配置 `.env`

宝塔环境示例：

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
```

### 5. 启动 API

```bash
python3 -m cert_auto_api.cli serve
```

### 6. 宝塔环境注意事项

- 如果 API 通过宝塔计划任务或守护进程启动，要确保启动用户能够执行 `crontab`
- 如果宝塔中有安全限制，需确认 Python 进程可以调用 `/www/server/panel/.acme.sh/acme.sh`
- 如果你使用反向代理公开 API，建议只通过 HTTPS 暴露

## 三、独立 Linux 环境配置

### 1. 适用情况

适用于：

- 未安装宝塔
- 使用官方脚本自行安装 `acme.sh`

本项目会自动尝试以下路径：

```text
/root/.acme.sh/acme.sh
~/.acme.sh/acme.sh
```

同时也会尝试 `PATH` 中的 `acme.sh`。

### 2. 安装 `acme.sh`

如果尚未安装，可使用官方方式安装。安装后通常会出现在：

```text
/root/.acme.sh/acme.sh
```

或当前用户的：

```text
~/.acme.sh/acme.sh
```

### 3. 建议部署目录

例如：

```bash
/opt/cert_auto_api
```

### 4. 安装依赖

```bash
cd /path/to/cert_auto_api
python3 -m pip install -r requirements.txt
cp .env.example .env
```

### 5. 配置 `.env`

独立环境示例：

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
```

### 6. 启动 API

```bash
python3 -m cert_auto_api.cli serve
```

### 7. 独立环境注意事项

- 若使用 root 安装 `acme.sh`，建议 API 也由同一权限级别用户运行
- 若 `acme.sh` 安装在当前用户目录，确保 API 进程由对应用户启动
- 若系统启用了防火墙，需要放行 `API_PORT`

## 四、服务端自动任务行为

服务端具备以下自动行为：

- API 启动时自动检查并补装服务端续签 `cron`
- 客户端访问证书相关 API 时，也会再次检查并补装 `cron`
- 服务端 `cron` 每天 `03:00` 检查证书
- 如果证书缺失或 15 天内到期，会触发后台续签

## 五、建议的上线方式

推荐顺序：

1. 先完成 Cloudflare DNS 接入
2. 配置 `.env`
3. 手动启动 API
4. 请求一次 `GET /healthz`
5. 请求一次 `GET /api/v1/certificate/info`
6. 确认服务端能正常识别 `acme.sh`
7. 再交给客户端定时拉取

## 六、排查建议

### 1. 服务端无法识别 `acme.sh`

优先检查：

- 宝塔 `acme.sh` 是否存在
- 自安装 `acme.sh` 是否位于常见路径
- 当前运行用户是否有权限执行 `acme.sh`

### 2. 服务端可以启动，但不能续签

优先检查：

- `CF_TOKEN` 是否正确
- `CERT_DOMAINS` 是否正确
- Cloudflare DNS 是否已接管
- 域名 `Nameserver` 是否已切到 Cloudflare

### 3. API 可访问，但客户端拿不到证书

优先检查：

- 服务端证书是否已经生成到 `CERT_OUTPUT_DIR`
- 当前是否仍在后台续签中
- `certificate/download` 是否返回了 `409`

