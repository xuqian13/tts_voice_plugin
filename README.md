# TTS 语音合成插件

MaiBot 的文本转语音插件，支持多种 TTS 后端引擎。

> **v3.3.0** — 已迁移到 MaiBot SDK 2.x（`MaiBotPlugin` + `@Action` / `@Command` + Pydantic 配置）。

## 支持的后端

| 后端 | 说明 | 适用场景 | 状态 |
|------|------|----------|------|
| GSV2P | 云端 API，需要 Token | 群聊/私聊 | ✅ 推荐 |
| GPT-SoVITS | 本地服务，需自行部署 | 群聊/私聊 | ✅ |
| 豆包语音 | 火山引擎云服务，高质量 | 群聊/私聊 | ✅ |
| CosyVoice | 阿里云 CosyVoice3，支持方言/声音克隆 | 群聊/私聊 | ✅ |
| 小米 MiMo | 小米 MiMo TTS，支持风格/方言/唱歌 | 群聊/私聊 | ✅ |
| AI Voice | MaiCore 内置 | — | ⚠️ **当前不可用**（见下） |

### ⚠️ AI Voice 后端在 MaiBot SDK 2.x 下不可用

AI Voice 后端依赖 `AI_VOICE_SEND` 平台原生命令通道，新版 SDK 把命令通道折回到 message_segment，napcat 适配器无法识别会发出 `[unsupported:command]` 文字到群里。

**插件已自动处理：** 当 LLM 选择 `ai_voice` 或用户用 `/voice` 命令时，插件会自动降级到默认后端合成语音，并在日志中给出 WARNING。`default_backend = "ai_voice"` 也会被自动改用 `gsv2p`。

## 安装

插件随 MaiBot 一起内置。若使用 CosyVoice 后端，需额外安装：

```bash
pip install gradio_client
```

## 配置

编辑 `plugins/tts_voice_plugin/config.toml`：

### 通用设置

```toml
[plugin]
enabled = true
config_version = "3.3.0"          # 配置文件版本，勿改

[general]
default_backend = "cosyvoice"     # 默认后端：gsv2p/gpt_sovits/doubao/cosyvoice/mimo
timeout = 60                      # 请求超时（秒）
max_text_length = 200             # 文本最大长度
use_replyer_rewrite = false       # 是否调用 LLM 二次润色（推荐 false，更稳定）
audio_output_dir = ""             # 音频输出目录，留空使用项目根目录
use_base64_audio = false          # true=base64 走 IPC；false=文件路径 voiceurl（更稳）
split_sentences = true            # 长文本分句逐段发送
split_delay = 0.3                 # 句子之间延迟（秒）
send_error_messages = true        # 合成失败时是否给用户提示

[components]
action_enabled = true             # LLM 自主触发的 Action 组件
command_enabled = true            # 用户手动 /tts 等命令

[probability]
enabled = false                   # 默认关闭概率门控（每次必发）
base_probability = 1.0
keyword_force_trigger = true
force_keywords = ["一定要用语音", "必须语音", "语音回复我", "务必用语音"]
```

### Docker 环境配置说明

**问题：** Docker 环境中可能遇到音频上传失败或文件路径识别错误。

**推荐顺序：**

1. **使用相对路径**（推荐）：`audio_output_dir = ""` 留空即可。
2. **自定义输出目录**：`audio_output_dir = "data/tts_audio"` 或绝对路径。
3. **使用 base64**：路径方案都不行时 `use_base64_audio = true`。

### 豆包语音

```toml
[doubao]
app_id = "你的APP_ID"
access_key = "你的ACCESS_KEY"
resource_id = "seed-tts-2.0"      # 预置音色；复刻音色用 seed-icl-2.0
default_voice = "zh_female_vv_uranus_bigtts"
sample_rate = 24000
bitrate = 128000
# speed / volume / context_texts 留默认（0.0 / 0.0 / []）即"不下发"
```

**预置音色：**

| 音色名称 | voice_type |
|----------|------------|
| vivi 2.0 | `zh_female_vv_uranus_bigtts` |
| 大壹 | `zh_male_dayi_saturn_bigtts` |
| 黑猫侦探社咪仔 | `zh_female_mizai_saturn_bigtts` |

**复刻音色：** `resource_id = "seed-icl-2.0"`，`default_voice` 填音色 ID（如 `S_xxxxxx`）。

凭证获取：[火山引擎控制台](https://console.volcengine.com/speech/service/8)

### GSV2P

```toml
[gsv2p]
api_url = "https://gsv2p.acgnai.top/v1/audio/speech"
api_token = "你的Token"
default_voice = "原神-中文-派蒙_ZH"
timeout = 120
model = "tts-v4"
response_format = "wav"
speed = 1.0
```

Token 获取：<https://tts.acgnai.top>

### GPT-SoVITS

```toml
[gpt_sovits]
server = "http://127.0.0.1:9880"

[[gpt_sovits.styles]]
name = "default"
refer_wav = "/path/to/reference.wav"
prompt_text = "参考音频对应的文本"
prompt_language = "zh"
gpt_weights = "/path/to/model.ckpt"      # 可选，动态切模型
sovits_weights = "/path/to/model.pth"    # 可选

[[gpt_sovits.styles]]
name = "happy"
refer_wav = "/path/to/happy.wav"
prompt_text = "开心的参考文本"
prompt_language = "zh"
```

### CosyVoice

```toml
[cosyvoice]
gradio_url = "https://funaudiollm-fun-cosyvoice3-0-5b.ms.show/"
default_mode = "3s极速复刻"            # 或 "自然语言控制"
default_instruct = "You are a helpful assistant. 请用湖南话表达。<|endofprompt|>"  # 仅自然语言控制模式生效
reference_audio = "/.../assets/test.wav" # 参考音频路径（3-10秒清晰人声）
prompt_text = "..."                     # 与参考音频对齐的文本
timeout = 300
audio_format = "wav"
```

**支持的方言/情感/语速：**

| 类型 | 可用选项 |
|------|----------|
| 方言 | 广东话、东北话、四川话、上海话、闽南话、山东话、陕西话、湖南话等 17 种 |
| 情感 | 开心、伤心、生气 |
| 语速 | 慢速、快速 |
| 音量 | 大声、小声 |
| 特殊风格 | 小猪佩奇、机器人 |

**推理模式：**
- `3s极速复刻`：用 `reference_audio` 做声音克隆
- `自然语言控制`：通过 `default_instruct` 控制方言/情感/语速

> 插件自带 `assets/test.wav` 示例参考音频，可直接用于 `3s极速复刻` 模式。

### 小米 MiMo

```toml
[mimo]
api_url = "https://api.xiaomimimo.com/v1/chat/completions"
api_key = "sk-xxxxxx"
model = "mimo-v2-tts"
default_voice = "mimo_default"     # mimo_default / default_zh / default_en
audio_format = "wav"
timeout = 60
user_context = ""                  # 可选的上下文文本（辅助调整语气）
```

API Key 申请：<https://platform.xiaomimimo.com>

**支持的 emotion：** 开心 / 悲伤 / 生气 / 东北话 / 四川话 / 粤语 / 唱歌 / 悄悄话 / 夹子音 / 台湾腔 等。

## 使用方法

### 命令触发（用户手动）

```
/tts 你好世界                    # 使用默认后端
/tts 今天天气不错 -v 小新         # 指定音色
/gsv2p 你好世界                  # 强制 GSV2P
/gptsovits 你好 -v happy         # 强制 GPT-SoVITS，使用 happy 风格
/doubao 我生气了 -v 生气          # 强制豆包，emotion=生气
/cosyvoice 你好 -v 广东话         # 强制 CosyVoice，方言=广东话
/mimo 真开心 -v 开心              # 强制 MiMo，emotion=开心
/tts help                         # 查看帮助
```

### 自动触发（LLM 决定）

MaiBot 的 planner 判断需要语音回复时，会自动调用 `unified_tts_action` 工具。可通过 `[probability]` 段控制概率：

```toml
[probability]
enabled = true            # 启用概率控制
base_probability = 0.3    # 30% 概率触发；其余降级文字
```

### 智能分割插件支持

本插件已适配智能分割插件，识别 `|||SPLIT|||` 分隔符精确分段：

- **优先级**：智能分割标记 > 自动句子分割 > 单句发送
- **示例**：`今天天气不错|||SPLIT|||适合出去玩|||SPLIT|||你觉得呢` → 三段语音依次发送

## 项目结构

```
tts_voice_plugin/
├── _manifest.json           # 插件 manifest v2
├── plugin.py                # 插件入口（MaiBotPlugin 子类）
├── config.toml              # 用户配置
├── config_keys.py           # 配置 key 常量
├── README.md                # 本文件
├── LICENSE                  # AGPL-3.0
├── assets/
│   └── test.wav             # CosyVoice 示例参考音频
├── backends/                # TTS 后端实现（策略模式）
│   ├── __init__.py          # 注册表
│   ├── base.py              # 抽象基类 + 工厂
│   ├── ai_voice.py
│   ├── gsv2p.py
│   ├── gpt_sovits.py
│   ├── doubao.py
│   ├── doubao_stream_parser.py
│   ├── cosyvoice.py
│   └── mimo.py
└── utils/                   # 工具层
    ├── text.py              # 文本清理/分句/语言检测
    ├── file.py              # 异步文件 IO / 临时文件
    └── session.py           # aiohttp 单例 session
```

## 常见问题

**Q: Docker 环境提示"文件处理失败 识别URL失败"？**
A: 留空 `audio_output_dir`，插件用项目根目录保存音频。仍有问题可设 `use_base64_audio = true`。

**Q: AI Voice 提示"自动降级到 gsv2p"？**
A: 见顶部说明 — 新版 MaiBot SDK 不支持 AI Voice 所需的命令通道，已自动改用其他后端，**不影响实际发音**。

**Q: 豆包语音怎么获取凭证？**
A: 登录火山引擎控制台，开通语音合成服务获取 `app_id` / `access_key` / `resource_id`。

**Q: 文本太长被截断？**
A: 改 `config.toml` 的 `max_text_length`（默认 200）。

**Q: 语音合成失败时不想让 Bot 发错误消息？**
A: `send_error_messages = false`，失败时静默处理。

**Q: 启动报"未找到 unified_tts_action / unified_tts_command"？**
A: 检查 `[components]` 是否被设为 `false`，或日志中是否有"已按配置禁用"。

**Q: LLM 主动调用语音时合成内容变成了"生成内容时出错"？**
A: 这是早期 bug，v3.3.0 已修。同时建议保持 `use_replyer_rewrite = false`，避免插件二次走 LLM。

## 已知限制

- **AI Voice 后端不可用**：新 SDK 命令通道未实现 `AI_VOICE_SEND`，已自动降级到其他后端。
- **LLM 二次润色默认关闭**：开启需在 `model_config.toml` 给 `replyer` 任务配可用 chat 模型，否则会取消润色直接用 planner 给的原始文本。
- **`use_base64_audio = true` 路径**：通过 IPC 传输 2MB+ 音频，少数 NapCat 配置下会发出空语音；推荐 `false` 走 voiceurl 文件路径。
- **临时音频文件清理延迟**：默认 180 秒后删，覆盖大多数慢传场景。

## 更新日志

### v3.3.0（MaiBot SDK 2.x 迁移）

**用户感知改进：**
- 修复 LLM 自主调用合成内容变成"生成内容时出错"的 bug（润色逻辑现在正确判断 success）
- LLM 润色显式使用 `replyer` 任务模型，与正常文字回复同源
- AI Voice 后端在新 SDK 下自动降级，不再误发 `[unsupported:command]` 文字
- `default_backend = "ai_voice"` 启动时自动改用 `gsv2p`
- `[components]` 开关真正生效（之前是假按钮）
- 配置 WebUI 现在能展示完整 11 段（之前 config.toml 0 字节导致看不到）

**开发侧改动：**
- 完整迁移到 `maibot_sdk`：`MaiBotPlugin` 基类 + `@Action` / `@Command` 装饰器 + Pydantic `PluginConfigBase`
- 新增 `create_plugin()` 工厂函数
- `_manifest.json` 升级到 v2，声明 capabilities：`chat.get_all_streams / llm.generate / send.command / send.custom / send.text`
- 删除所有 `from src.common.logger` 依赖，改用标准 `logging.getLogger`
- backends 与 utils 层不再依赖 `src.*`
- 收敛宽 `except Exception`，区分 `TimeoutError / ClientError / KeyError-AttributeError-TypeError`
- CosyVoice `Client(...)` 构造下沉到 `asyncio.to_thread`，避免阻塞事件循环
- 临时音频文件清理延迟 30s → 180s
- 删除从未使用的 `[action_trigger]` 配置段
- `test.wav` 移到 `assets/` 子目录
- 配置桥接层：扁平 key → Pydantic 嵌套；哨兵值翻译（doubao.speed=0.0 → None）

### v3.2.3
- 修复豆包 WAV 流式响应合并问题（正确处理 LIST/INFO 元数据块）
- 默认后端改为 CosyVoice
- 默认关闭概率控制
- 优化 LLM 长度约束提示
- GSV2P/豆包音频格式默认改为 WAV
- 更新默认超时配置（CosyVoice 300s, GSV2P 120s）

### v3.2.2
- 适配智能分割插件（`|||SPLIT|||`）
- GPT-SoVITS 支持数组格式配置（WebUI 友好）
- 修复豆包语音音色信息显示乱码
- 禁用 Python 字节码生成

### v3.2.0
- 新增 CosyVoice 后端
- 新增分段发送功能
- GPT-SoVITS 支持动态模型切换
- GSV2P 新增重试机制
- 新增 `/cosyvoice` 命令

### v3.1.0
- 新增豆包语音后端
- 重构为模块化架构
- HTTP Session 复用优化

## 信息

- **版本**：3.3.0
- **原作者**：靓仔
- **MaiBot SDK 2.x 适配**：靓仔
- **许可**：AGPL-3.0-or-later
- **插件 ID**：`xuqian13.tts-voice-plugin`
