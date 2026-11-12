# Chat_AI v241.0 Mod 2API

> `com.msc.ai.chat.bot.aichat` (v241.0) 逆向 → OpenAI 兼容 2API
> 多通道聚合：begamob v2（主文本）+ Vulcan（备文本）+ goatchat（生图）

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)

## 原理

本 APK 是 begamob/ikameglobal 白标家族的多上游聚合聊天 App，聊天请求按优先级路由五个上游。逆向还原出三个可用通道：

| 通道 | 端点 | 鉴权 | 用途 |
|------|------|------|------|
| **begamob v2** | `chat-ai.begamob.com/api/v2/chatStream` | 客户端本地自签 HS256 JWT（密钥硬编码于 APK `F8.b`） | 主文本通道，SSE 流式，模型 `gpt-4o-mini` |
| **Vulcan** | `api.vulcanlabs.co/smith-v2/api/v7/chat_android` | 免费设备注册 JWT（30min，可无限重放） | 备用文本通道，自动降级 |
| **goatchat** | `api.goatchat.ai/v1/*` | 免费设备注册 JWT（永久，exp 2038） | Journey AI 文生图 |

**关键协议细节**（完整版见 [ANALYSIS.md](ANALYSIS.md)）：

- begamob JWT payload：`{iat, exp: iat+900, bundleId: "com.chat.chatai.chatbot.aichatbot", os: "Android", versionApp: "1.2.2", timezone}`，密钥经 `Y3.A3.a()` base64-XOR 变形后作 HMAC-SHA256 key；请求另带 `user-header` 拼接串（bundleId/versionApp/osVersion/uid/deviceId）
- Vulcan 响应的 message 字段是大写 `choices[0].Message`，且是 **dict**（`{role, content}`）而非字符串
- begamob 开启联网搜索：body 加 `"tools": ["search_web"]`，SSE 中 `contentType == "web_search_source"` 时 `webs` 字段带来源
- goatchat TEXT bot 全部被 Boost 订阅墙锁死（`422 code=101057`），仅 IMAGE bot 可用

## 快速开始

```bash
pip install -r requirements.txt  # 无第三方依赖，纯标准库（此文件仅为兼容惯例，可跳过）
python demo_server.py
```

需要代理出网时（如本机 clash）：

```bash
# Windows PowerShell
$env:CHAT_AI_PROXY_HOST = "127.0.0.1"; $env:CHAT_AI_PROXY_PORT = "10808"; python demo_server.py

# Linux / macOS
CHAT_AI_PROXY_HOST=127.0.0.1 CHAT_AI_PROXY_PORT=7890 python demo_server.py
```

- Demo 页面：`http://127.0.0.1:8918`
- 健康检查：`GET /health`
- 模型列表：`GET /v1/models`

## OpenAI 兼容接口

### Chat（流式 / 非流式）

```bash
curl http://127.0.0.1:8918/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "stream": true, "messages": [{"role": "user", "content": "你好"}]}'
```

| 模型名 | 行为 |
|--------|------|
| `gpt-4o-mini` | begamob 主通道（失败自动降级 vulcan） |
| `gpt-4o-mini-search` | 同上 + 联网搜索（响应含 `[web_search_source]` 来源块） |
| 其它任意模型名 | 上游钉死 `gpt-4o-mini`，正常路由（不报错） |

### 生图

```bash
curl http://127.0.0.1:8918/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a red sports car at sunset"}'
```

返回标准 OpenAI images 格式，`meta` 附带宽高与通道信息（goatchat Journey AI，1024x768）。

## new-api 对接

见 [docs/NEW-API-INTEGRATION.md](docs/NEW-API-INTEGRATION.md)。要点：渠道类型选 OpenAI(1)，BaseURL **不带** `/v1`，模型填 `gpt-4o-mini`（+可选 `gpt-4o-mini-search`），超时 ≥180s，重试 1-2 次，权重调低（上游免费层，建议作为备用渠道而非主力）。

## 压测

```bash
python stress_test.py            # 标准 12 场景
python stress_test.py --extreme  # + 阶梯并发 20/30/50
```

实测记录（2026-11-12，详见 ANALYSIS.md §4）：

```
[PASS] health          7.4ms
[PASS] baseline_5x     p50 3767ms
[PASS] stream_basic    3889ms
[PASS] concurrency_5x10   10/10, wall 4.0s
[PASS] concurrency_10x20  20/20, wall 17.5s
[PASS] continuous_15x2    0 失败 0 限流
[PASS] boundary_20k    20K 字符通过
[PASS] boundary_empty/badjson/nomsg  400 拦截全对
[PASS] image_gen       8319ms
===== 12/12 PASS =====
extreme: c20 20/20, c30 30/30, c50 46/50
```

**降级验证**：begamob 被 Cloudflare 封禁期间（出口 IP 限流），118 连续请求全部由 vulcan 自动接管，`vulcan_fail=0`。

## Mod 分析结论

- Mod 载体：`assets/SignatureKiller/origin.apk`（38MB 原包）+ 双架构 `libSignatureKiller.so`，运行时伪造签名上下文过校验；**未发现**独立恶意 dex 注入或数据外传通道
- Mod 作者：`t.me/leeapk_official`
- 附带发现：原包内含开发者泄露的**活 Telegram bot token**（错误上报用，固定 chat_id），属上游凭证泄露而非 Mod 添加，本仓库不记录其值

## 已知边界

1. begamob/vulcan 均在 Cloudflare 层按出口 IP 限流（高频触发 429 HTML；vulcan 冷却 20-30min，begamob 封禁更久）
2. goatchat 文本 bot 被 Boost 订阅墙锁死（服务端配额），仅生图可用
3. chaton / syphnosys 通道未破解（native 鉴权 / 动态配置，需 Frida 动态分析）
4. vulcan 降级时为单块伪流式（上游 v7 无真流式）

## 免责声明

本项目仅供安全研究与协议学习。所有上游端点均通过公开分发的 APK 静态分析获得；请勿用于商业用途或对上游服务造成负担。使用者自行承担相应责任。

## License

[MIT](LICENSE)
