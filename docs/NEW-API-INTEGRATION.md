# new-api 对接指南（Chat_AI v241 2API）

本 demo server 提供标准 OpenAI 兼容接口，可直接对接 [new-api](https://github.com/QuantumNous/new-api)（及 one-api 系衍生）。

## 渠道配置

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 类型 | **OpenAI (1)** | 标准 OpenAI 协议 |
| Base URL | `http://<你的服务器IP>:8918` | **不要带** `/v1` 后缀（new-api 自动拼接） |
| 模型 | `gpt-4o-mini` | 必填；可选追加 `gpt-4o-mini-search`（联网搜索变体） |
| 模型重定向 | 留空 | 上游钉死 `gpt-4o-mini`，重定向无意义 |
| 密钥 | 任意非空字符串（如 `sk-chatai241`） | 本 server 不校验 key |
| 超时 | **180** 秒 | 生图通道（goatchat）单请求可达 60-120s |
| 重试 | 1-2 次 | begamob 偶发 CF 429，降级 vulcan 后一般一次成功 |
| 权重 | **调低**（如 1-10） | 免费上游不稳定（CF 限流），建议作备用渠道 |
| 分组 | default | |
| 状态码复写 | 留空 | |

## 部署 demo server（供 new-api 调用）

```bash
# 与 new-api 同机部署（推荐，免代理）
git clone https://github.com/lza6/Chat-AI-APP-2api.git
cd Chat-AI-APP-2api
python demo_server.py              # 默认 127.0.0.1:8918

# 监听所有网卡（供远程 new-api 调用）——修改 PORT 绑定或用端口转发
# 注意：本 server 无鉴权，公网暴露请自行加反代鉴权或 IP 白名单
```

## 对接步骤（new-api 后台）

1. **渠道 → 添加渠道**
2. 类型选 `OpenAI`，名称随意（如 `chatai-241-free`）
3. Base URL 填 `http://127.0.0.1:8918`（同机）或服务器实际地址
4. 模型框填：`gpt-4o-mini`（换行添加 `gpt-4o-mini-search` 如需搜索）
5. 密钥填任意值，提交
6. **测试**：渠道列表点「测试」，模型选 `gpt-4o-mini`，应返回 200 与回复内容
7. 令牌侧正常创建令牌即可调用

## 验证命令

```bash
# 经 new-api 网关调用（假设 new-api 在 :3000，令牌 sk-xxx）
curl http://127.0.0.1:3000/v1/chat/completions \
  -H "Authorization: Bearer sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "stream": false, "messages": [{"role": "user", "content": "1+1=?"}]}'

# 生图
curl http://127.0.0.1:3000/v1/images/generations \
  -H "Authorization: Bearer sk-xxx" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a lighthouse at dawn"}'
```

## 行为说明

- **流式**：`stream: true` 走 begamob SSE 真流式；降级 vulcan 时为单块伪流式（上游不支持真流式）
- **降级**：begamob 失败（含 CF 429）自动切 vulcan，对调用方透明
- **计费倍率**：模型虽名 `gpt-4o-mini`，实际为上游免费层，建议在 new-api「模型固定价格」中按需设置倍率（或保持默认）
- **限流特征**：若日志出现 `429` 与 Cloudflare HTML，为出口 IP 被 CF 限流；vulcan 冷却约 20-30 分钟，begamob 更久。建议低权重 + 其它渠道互补
- **search 变体**：`gpt-4o-mini-search` 的响应中会出现 `[web_search_source][...]` 块（JSON 来源列表），前端如需展示请自行解析；new-api 直接透传不影响计费

## 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| 渠道测试返回 502 | 本机出网需代理但未配置 | 设 `CHAT_AI_PROXY_HOST/PORT` 环境变量后重启 |
| 测试超时 | goatchat 生图慢 / CF 限流中 | 超时调到 180s；或稍等冷却 |
| 模型返回空 content | begamob 流式中断 | 重试一次（自动降级 vulcan） |
| images 接口 502 | goatchat 偶发无图返回 | 重试；goatchat 免费层生图稳定但偶发空响应 |
