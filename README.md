# TTS 语音合成插件

MaiBot 的文本转语音插件，支持多种 TTS 后端。

## 支持的后端

| 后端 | 说明 | 适用场景 |
|------|------|----------|
| AI Voice | MaiCore 内置，无需配置 | 仅群聊 |
| GSV2P | 云端 API，需要 Token | 群聊/私聊 |
| GPT-SoVITS | 本地服务，需自行部署 | 群聊/私聊 |
| 豆包语音 | 火山引擎云服务，高质量 | 群聊/私聊 |

## 安装

```bash
pip install aiohttp
```

## 配置

编辑 `config.toml`，设置默认后端：

```toml
[general]
default_backend = "doubao"     # 可选：ai_voice / gsv2p / gpt_sovits / doubao
audio_output_dir = ""          # 音频输出目录，留空使用项目根目录
use_base64_audio = false       # 是否使用base64发送（备选方案）
```

### Docker环境配置说明

**问题：** Docker环境中可能遇到音频上传失败或文件路径识别错误（如`识别URL失败`）

**解决方案（按推荐顺序）：**

#### 方案1：使用相对路径（推荐）

```toml
[general]
audio_output_dir = ""  # 留空，默认使用项目根目录
```

音频文件将保存在项目根目录，OneBot/NapCat可以正确识别相对路径。

#### 方案2：自定义输出目录

```toml
[general]
audio_output_dir = "data/tts_audio"  # 相对路径，相对于项目根目录
# 或
audio_output_dir = "/app/data/audio" # 绝对路径
```

#### 方案3：使用base64编码（备选）

如果路径方案都不生效，可启用base64发送：

```toml
[general]
use_base64_audio = true  # 使用base64编码发送（会增加约33%数据大小）
```

### 豆包语音配置

```toml
[doubao]
app_id = "你的APP_ID"
access_key = "你的ACCESS_KEY"
resource_id = "seed-tts-2.0"
default_voice = "zh_female_vv_uranus_bigtts"
```

**预置音色：**

| 音色名称 | voice_type |
|----------|------------|
| vivi 2.0 | zh_female_vv_uranus_bigtts |
| 大壹 | zh_male_dayi_saturn_bigtts |
| 黑猫侦探社咪仔 | zh_female_mizai_saturn_bigtts |

**复刻音色：** 将 `resource_id` 改为 `seed-icl-2.0`，`default_voice` 填音色 ID（如 `S_xxxxxx`）

凭证获取：[火山引擎控制台](https://console.volcengine.com/speech/service/8)

### GSV2P 配置

```toml
[gsv2p]
api_token = "你的Token"
default_voice = "原神-中文-派蒙_ZH"
```

Token 获取：[https://tts.acgnai.top](https://tts.acgnai.top)

### AI Voice 配置

```toml
[ai_voice]
default_character = "温柔妹妹"
```

可用音色：小新、猴哥、妲己、酥心御姐、温柔妹妹、邻家小妹 等 22 种

### GPT-SoVITS 配置

```toml
[gpt_sovits]
server = "http://127.0.0.1:9880"

[gpt_sovits.styles.default]
refer_wav = "/path/to/reference.wav"
prompt_text = "参考文本"
```

## 使用方法

### 命令触发

```
/tts 你好世界                    # 使用默认后端
/tts 今天天气不错 小新            # 指定音色
/gsv2p 你好世界                  # 使用 GSV2P
/doubao 你好世界                 # 使用豆包
```

### 自动触发

LLM 判断需要语音回复时会自动触发，可通过概率控制：

```toml
[probability]
enabled = true
base_probability = 0.3  # 30% 概率
```

## 项目结构

```
tts_voice_plugin/
├── plugin.py          # 插件入口
├── config.toml        # 配置文件
├── backends/          # 后端实现
│   ├── ai_voice.py
│   ├── gsv2p.py
│   ├── gpt_sovits.py
│   └── doubao.py
└── utils/             # 工具函数
```

## 常见问题

**Q: Docker环境中提示"文件处理失败 识别URL失败"？**
A: 留空 `audio_output_dir` 配置项，插件将使用项目根目录保存音频（相对路径）。如仍有问题，可设置 `use_base64_audio = true` 使用base64编码发送。

**Q: AI Voice 提示"仅支持群聊"？**
A: AI Voice 只能在群聊使用，私聊会自动切换到其他后端。

**Q: 豆包语音怎么获取凭证？**
A: 登录火山引擎控制台，开通语音合成服务获取。

**Q: 文本太长被截断？**
A: 修改 `config.toml` 中 `max_text_length = 1000`

## 信息

- 版本：3.1.0
- 作者：靓仔
- 许可：AGPL-v3.0
