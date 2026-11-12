# Chat_AI v241.0 (241) Mod — 逆向分析报告

- **APK**: `Chat_AI_v241.0_(241)_Mod.apk` (44.1 MB)
- **包名**: `com.msc.ai.chat.bot.aichat`
- **白标来源**: `com.chat.chatai.chatbot.aichatbot` (F8.b 内嵌常量) — ikameglobal/begamob 家族
- **版本**: 241.0 (241), minSdk 26, AGP 8.4.0
- **Mod 注入**: `assets/SignatureKiller/origin.apk` (38.6MB 原包, 2026-05-19 15:56 注入) + `lib/armeabi-v7a|arm64-v8a/libSignatureKiller.so` — 过签名校验方案，与 AI_Art_2.1.0.1 (ZERO_MODS) 同源
- **Mod 作者**: `classes3.dex` 内 `t.me/leeapk_official`
- **工作目录**: `D:/apk-analysis/chatai-241/`，jadx 反编译 7127 类 (27 错误)

---

## 1. 架构：五通道聊天聚合

本 APK 是一个多上游聚合白标。聊天请求按优先级路由，失败自动降级：

| # | 通道 | 端点 | 鉴权 | 状态 |
|---|------|------|------|------|
| 1 | **begamob v2** (主) | `https://chat-ai.begamob.com/api/v2/chatStream` | 本地自签 HS256 JWT（密钥硬编码在 APK） | R1 打通，后触发 CF 限流 |
| 2 | **Vulcan** (备) | `https://api.vulcanlabs.co/smith-v2/api/v7/chat_android` | 免费设备注册 JWT (30min) | R1 打通 |
| 3 | **goatchat** (生图) | `https://api.goatchat.ai/v1/*` | 免费设备注册 JWT (永久, exp 2038) | R1 打通 (IMAGE bot) |
| 4 | **syphnosys** | URL 即鉴权 + form | 静态 key `LIVE-V700-...` | 端点存活，静态 key 被拒 (`Invalid API Key`)，疑 Remote Config 动态下发 |
| 5 | **chaton/emoji-keyboard** | `chat.emoji-keyboard.com/api/v2/Chat` | `liblib_native.so::getAuthHeader` (native HMAC) | 未打通（需 R2 动态） |

### 1.1 begamob v2 (主通道) — 核心逆向成果

**鉴权完全离线**：JWT 在客户端本地签名，服务端仅验签。签名密钥 `stteam-ikameglobal-chatapiopenai` 硬编码于 `F8.b.f2307h`，经 `Y3.A3.a()` 变形（≤50 字符直接过 `O3.b` base64 XOR 变换）后作为 HMAC-SHA256 key。

```
JWT payload (exp = iat + 900s):
{ "iat": <now>, "exp": <now+900>,
  "bundleId": "com.chat.chatai.chatbot.aichatbot",
  "os": "Android", "versionApp": "1.2.2", "timezone": "<IANA tz>" }
```

请求头:
- `Authorization: Bearer <自签JWT>`
- `user-header: bundleId:.../versionApp:1.2.2/OS:Android/osVersion:29/<32hex uid>/<64hex deviceId>`

请求体（模型硬编码 `gpt-4o-mini`，服务端忽略其它值）:
```json
{ "messages": [{"role":"user","content":[{"type":"text","text":"..."}]}],
  "model": "gpt-4o-mini", "response_length": "", "response_tone": "",
  "topic_type": "", "image_and_analytic": true }
```

响应: SSE `data:` 逐行，`data.content` 增量文本，`data.contentType == "web_search_source"` 时 `data.webs` 带搜索来源。`tools: ["search_web"]` 开启联网搜索。

**验证记录**: `9+10=19`、`13*13=169` 端到端返回正确；触发 CF 限流后端点返回 Cloudflare HTML 429（限流在 CF 层非应用层，冷却后应恢复）。

### 1.2 Vulcan 备通道

与 AI ChatBot v10 (Chat Smith) 同族协议：
- `POST /smith-auth/api/v1/token` body `{device_id: <uuid>, ...空}` → 免费 30min JWT (`tier=free`)
- `POST /smith-v2/api/v7/chat_android` → 标准格式响应，但字段是大写 `choices[0].Message`
- **验证记录**: `8*7=56` ✓ (真实上游模型 `gpt-4o-mini-2024-07-18`)
- 极限压测期间同样触发 CF 429（token 端点），与 begamob 一致为代理出口 IP 限流

### 1.3 goatchat (生图通道)

- `POST /v1/auth` — 设备信息注册即发 token，**exp 到 2038 年（永久）**，无密钥校验、无验证码
- `GET /v1/bots` — 10 个 bot (Journey AI / Anime AI / Emoji AI 为 IMAGE 型；9 个 TEXT 型)
- `GET /v1/bots/{id}/chat` 创建会话；`POST /v1/chats/{id}/message` body `{"message": "..."}`
- **IMAGE bot 完整打通**: 两次生图成功 (1024x768, replicate.delivery CDN)
- **TEXT bot 全部返回空文本**: 实测 5 个 bot × 多种参数变体，BOT 消息 `text=""`，随后触发 `422 code=101057 "not subscribed to Boost"` — 免费层文本生成被 Boost 订阅墙锁死（图片不受限）。这是**服务端配额**，非客户端可绕过

### 1.4 syphnosys 通道

`B2.f8052a` URL 即完整鉴权（路径含 token 段），POST form `app_version=77&ai_prompt=<prompt>&api_auth=LIVE-V700-5T8T-8J6E-W5J6-J8R1-1D8Y-6K4A-R5H8-C6E0-6R4Z-7H5D-T8E9-U5S6-8T9E-6J4S`。
响应为标准 OpenAI 格式 (`choices[0].message.content`)。实测返回 `{"detail":"Invalid API Key"}` — key 有效期机制或经 Firebase Remote Config 动态覆盖（该家族惯用手法，见 ChatAI 35.x）。

### 1.5 chaton 通道 (未破解)

`AbstractC0364u` 配置 + `NativeLib().getAuthHeader(url, method, body)` — 鉴权头由 `liblib_native.so` 生成，与记忆中 AI ChatBot v10 的 ChatKey/ChatOn 卡点一致，需 Frida 动态 hook（R2 范畴）。

---

## 2. Mod 分析（安全审计）

| 项 | 结论 |
|----|------|
| Mod 载体 | `assets/SignatureKiller/origin.apk` + `libSignatureKiller.so`（双架构），运行时以原包签名欺骗系统 |
| Mod 注入代码 | 无独立 dex 注入（对比 AI_Art 的 `com.modsx.zero` 弹窗方案，本包未发现宣传/跳转代码） |
| Mod 作者痕迹 | `classes3.dex`: `https://t.me/leeapk_official` |
| **泄露的活凭证** | **原开发者的 Telegram 错误上报 bot token（完整值已从本报告抹除，仅存于 APK classes.dex）**，`A8.b` case 3 发往固定群组 `chat_id=-9279****949`。这是原始包自带的（非 Mod 添加），token 仍然有效，属于上游的凭证泄露。已在公开交付中隐去完整值 |
| 内购破解 | Standard SignatureKiller 方案（origin.apk 内为原版计费逻辑，运行时替换签名上下文） |
| 隐私风险 | 无额外数据外传通道；telemetry 走 TikTok/Facebook/Google SDK（原包行为） |

## 3. 交付物

```
D:/apk-analysis/chatai-241/
├── demo_server.py    # :8918 OpenAI 兼容 2API (begamob 主 + vulcan 降级 + goatchat 生图)
├── demo.html         # 中文流式聊天 + Journey AI 生图面板 + 实时健康/stats
├── stress_test.py    # 12 标准场景 + 3 极限阶梯
├── ANALYSIS.md       # 本报告
├── jadx_out/         # 反编译源码 (7127 类)
├── raw/              # APK 解包产物
└── server.log        # 运行日志
```

## 4. 压测记录 (R1)

### 终轮 (降级链路验证, begamob 处于 CF 封禁期间)

| 场景 | 结果 |
|------|------|
| health | PASS 7.4ms |
| 基线 5x | PASS 5/5, p50 3767ms |
| 流式 | PASS "1 2 3 4 5", 3889ms |
| 并发 5x10 | PASS 10/10, wall 4.0s, p50 2893ms |
| 并发 10x20 | PASS 20/20, wall 17.5s, p50 8982ms |
| 连续 15x2 | PASS 0 失败 0 限流, p50 2788ms |
| 20K 边界 | PASS (55 字摘要回复) |
| 空/坏JSON/缺messages | 400 拦截全对 |
| 未知模型 | PASS 路由正常 (上游钉死 gpt-4o-mini) |
| goatchat 生图 | PASS 8319ms |
| 极限 c20/c30 | **20/20 + 30/30 全 200** (vulcan 承载) |
| **总计** | **12/12 PASS** |

**降级链路验证**: begamob 被 CF 封禁期间，118 连续请求全部由 vulcan 自动接管，`vulcan_fail=0`。多通道聚合设计经实测有效。

### 早期极限 (begamob 可用期)

| 场景 | 结果 |
|------|------|
| 极限并发 20 | 20/20 全 200, wall 5.8s, p50 3181ms |
| 极限并发 30 | 30/30 全 200, wall 7.2s, p50 5065ms |
| 极限并发 50 | 46/50, wall 5.1s, p50 3402ms |

**限流结论**: begamob/vulcan 均在 Cloudflare 层按出口 IP 限流。vulcan 冷却约 20-30 分钟后恢复；begamob 封禁持续 45+ 分钟仍未解除（单请求探测仍 429 HTML）。协议层已验证无其他限制。本机代理出口 (127.0.0.1:10808) 高频命中是封禁诱因。

## 5. 已知边界

1. begamob CF 封禁 45+ 分钟未解除（vulcan 约 20-30 分钟恢复）；恢复前文本全走 vulcan，功能无损
2. goatchat 文本 bot 被 Boost 订阅墙锁死（服务端配额，无法客户端绕过）
3. chaton / syphnosys 需 R2 动态（Frida hook `liblib_native.so::getAuthHeader` / Remote Config 拉取）
4. Telegram bot token 是活凭证，已在报告中标注（不写入 demo_server）
5. 流式场景下 vulcan 降级为单块伪流式（上游 v7 无真流式）
