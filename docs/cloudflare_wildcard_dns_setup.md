# Cloudflare DNS 泛域名申请准备说明

本文档用于说明在使用 `dns_cf` 方式签发主域名和泛域名证书前，需要先完成的 Cloudflare 域名接入与 DNS 设置。

适用场景：

- 你要申请 `example.com` 和 `*.example.com`
- 你准备使用 `acme.sh --dns dns_cf`
- 你需要先把域名 DNS 托管到 Cloudflare

## 1. 注册并登录 Cloudflare

1. 访问 Cloudflare 官网并注册账号
2. 登录 Cloudflare 控制台
3. 确保你的邮箱已完成验证

## 2. 将域名添加到 Cloudflare

1. 在 Cloudflare 控制台点击添加站点
2. 输入你的主域名，例如 `example.com`
3. 选择适合你的套餐
4. 等待 Cloudflare 扫描现有 DNS 记录

说明：

- Cloudflare 通常会自动导入现有 DNS 记录
- 导入后请人工检查，避免遗漏关键记录

## 3. 修改域名 Nameserver

Cloudflare 接管 DNS 的关键步骤是把域名注册商处的 `Nameserver` 修改为 Cloudflare 提供的 `Nameserver`。

操作方式：

1. 在 Cloudflare 中查看该域名对应的两个 `Nameserver`
2. 登录你的域名注册商后台
3. 找到域名 DNS 或 `Nameserver` 管理页面
4. 删除原有 `Nameserver`
5. 替换为 Cloudflare 提供的两个 `Nameserver`
6. 保存修改并等待全球生效

说明：

- 只有当域名真正切换到 Cloudflare `Nameserver` 后，`dns_cf` 才能正常生效
- 生效时间可能是几分钟到数小时不等

## 4. 添加和检查 DNS 记录

为了申请如下证书：

```text
example.com
*.example.com
```

建议至少检查或添加以下记录：

- 主机名 `@`
- 主机名 `*`

常见记录示例：

```text
类型: A
主机名: @
内容: 你的服务器 IP

类型: A
主机名: *
内容: 你的服务器 IP
```

说明：

- `@` 代表主域名，例如 `example.com`
- `*` 代表泛域名，例如 `*.example.com`
- 如果你的服务使用 IPv6，也可以同时配置 `AAAA` 记录

## 5. 关闭 Cloudflare 代理

在申请证书阶段，建议将相关 DNS 记录设置为仅 DNS，不使用 Cloudflare 代理。

需要检查：

- `@` 记录
- `*` 记录

应设置为：

- 灰云
- DNS only

不要设置为：

- 橙云
- Proxied

说明：

- 对 `dns_cf` 来说，DNS 记录本身由 API 控制
- 但在实际业务使用中，主域名和泛域名记录建议先保持 `DNS only`
- 这样排查 DNS、生效和证书问题更直接

## 6. 创建 Cloudflare API Token

你需要创建一个供 `acme.sh` 使用的 API Token。

建议权限：

- Zone
  - DNS
    - Edit
- Zone
  - Zone
    - Read

作用范围：

- 建议仅授权到目标域名所在的 Zone

创建后：

1. 复制这个 Token
2. 填入项目 `.env` 中的 `CF_TOKEN`

例如：

```env
CF_TOKEN=your_cloudflare_token
```

## 7. 验证配置

在本项目中，典型配置如下：

```env
CERT_DOMAINS=example.com,*.example.com
CF_TOKEN=your_cloudflare_token
```

程序会：

- 自动识别主域名为 `example.com`
- 使用 Cloudflare DNS API 完成 TXT 验证
- 申请一张同时包含主域名和泛域名的证书

## 8. 常见问题

### Nameserver 已改但仍未生效

可能原因：

- 注册商侧修改未完全生效
- 本地 DNS 缓存尚未更新
- Cloudflare 尚未完成域名激活

### 申请失败提示没有权限

优先检查：

- `CF_TOKEN` 是否正确
- Token 是否包含 DNS 编辑权限
- Token 是否授权到了正确的 Zone

### 泛域名解析不生效

优先检查：

- 是否添加了 `*` 记录
- 是否错误开启了代理
- 是否存在更具体的子域名记录覆盖

## 9. 建议

- 先完成 Cloudflare 接管和 DNS 检查，再启动本项目
- 首次部署时，建议手动调用一次续签检查接口或命令
- 如果证书申请失败，优先检查 `Nameserver`、`CF_TOKEN` 和 DNS 记录状态
