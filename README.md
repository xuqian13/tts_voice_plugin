# TTS语音合成插件

统一的文本转语音插件，支持三种后端引擎的灵活切换。

## 功能特性

### 三种后端引擎

| 后端 | 类型 | 特点 | 使用场景 |
|------|------|------|----------|
| **AI Voice** | MaiCore内置 | 简单快速，22种音色，无需配置 | 群聊语音（仅限群聊） |
| **GSV2P** | 云端API | 高质量合成，丰富参数调节 | 私聊和群聊，需要API Token |
| **GPT-SoVITS** | 本地服务 | 高度定制化，支持多风格 | 自建服务，需要本地部署 |

### 两种触发方式

1. **自动触发** - LLM智能判断，自动使用语音回复
2. **手动触发** - 使用命令主动转换文本为语音

## 快速开始

### 1. 安装依赖

```bash
pip install aiohttp
```

### 2. 基础配置

编辑 `config.toml`：

```toml
[plugin]
enabled = true

[general]
default_backend = "ai_voice"  # 默认使用AI Voice
timeout = 60
max_text_length = 500
```

### 3. 配置后端

#### 使用AI Voice（无需额外配置）

```toml
[ai_voice]
default_character = "温柔妹妹"
# 支持22种音色，详见配置文件
```

#### 使用GSV2P（需要API Token）

```toml
[gsv2p]
api_url = "https://gsv2p.acgnai.top/v1/audio/speech"
api_token = "your_api_token_here"  # 填写你的API Token
default_voice = "原神-中文-派蒙_ZH"
```

#### 使用GPT-SoVITS（需要本地服务）

```toml
[gpt_sovits]
server = "http://127.0.0.1:9880"

[gpt_sovits.styles.default]
refer_wav = "/path/to/reference.wav"
prompt_text = "参考文本"
prompt_language = "zh"
```

## 使用方法

### 命令触发

```bash
# 基础用法（使用默认后端和音色）
/tts 你好世界

# 指定音色
/tts 今天天气不错 小新

# 指定后端
/tts 测试一下 温柔妹妹 ai_voice

# 使用GSV2P
/gsv2p 你好世界

# 使用GSV2P指定音色
/tts 你好 原神-中文-派蒙_ZH gsv2p
```

### AI Voice 音色列表

```
小新、猴哥、四郎、东北老妹儿、广西大表哥
妲己、霸道总裁、酥心御姐、说书先生、憨憨小弟
憨厚老哥、吕布、元气少女、文艺少女、磁性大叔
邻家小妹、低沉男声、傲娇少女、爹系男友、暖心姐姐
温柔妹妹、书香少女
```

### LLM自动触发

当LLM判断需要使用语音回复时，会自动触发。你可以在配置中调整概率：

```toml
[probability]
enabled = true  # 启用概率控制
base_probability = 0.3  # 30%概率触发
keyword_force_trigger = true  # 关键词强制触发
force_keywords = ["一定要用语音", "必须语音", "语音回复我"]
```

## 配置说明

### 通用配置

```toml
[general]
default_backend = "ai_voice"  # 默认后端: ai_voice/gsv2p/gpt_sovits
timeout = 60                  # 请求超时时间（秒）
max_text_length = 500         # 最大文本长度
```

### 组件控制

```toml
[components]
action_enabled = true   # 启用自动触发（LLM判断）
command_enabled = true  # 启用命令触发
```

### 概率控制

```toml
[probability]
enabled = false              # 是否启用概率控制
base_probability = 0.3       # 基础触发概率（0.0-1.0）
keyword_force_trigger = true # 关键词强制触发
force_keywords = ["一定要用语音", "必须语音"]
```

## 常见问题

### Q: AI Voice提示"仅支持群聊"？
**A:** AI Voice是MaiCore内置功能，只能在群聊中使用。如需私聊语音，请使用GSV2P或GPT-SoVITS后端。

### Q: GSV2P报错"缺少API Token"？
**A:** 在 `config.toml` 中配置你的API Token：
```toml
[gsv2p]
api_token = "your_token_here"
```

### Q: 如何获取GSV2P API Token？
**A:** 访问 [GSV2P官网](https://tts.acgnai.top) 注册账号并获取Token。

### Q: GPT-SoVITS提示"API调用失败"？
**A:** 确保本地GPT-SoVITS服务正在运行，并检查配置中的服务地址是否正确。

### Q: 语音不清晰或有问题？
**A:**
1. 调整GSV2P参数（`temperature`、`top_k`、`top_p`）
2. 尝试更换音色
3. 简化文本内容，避免特殊字符

### Q: 如何切换默认后端？
**A:** 修改 `config.toml` 中的 `default_backend`：
```toml
[general]
default_backend = "gsv2p"  # 改为gsv2p
```

### Q: 文本被截断？
**A:** 调整最大文本长度：
```toml
[general]
max_text_length = 1000  # 增加到1000字符
```

## 技术支持

- **版本**: 3.0.0
- **作者**: 靓仔
- **依赖**: aiohttp
- **兼容**: MaiCore 0.9.0+

## 许可证

本插件采用 AGPL-v3.0 许可证。

