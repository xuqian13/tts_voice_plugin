# GPT-SoVITS 语音合成插件

基于 GPT-SoVITS 的文本转语音（TTS）插件，为 MaiBot 提供高质量的多语言语音合成功能。

## 功能特性

- **多语言支持**：自动识别中文、英文、日文
- **多风格配置**：支持自定义多种语音风格
- **智能触发**：通过关键词自动触发语音合成
- **文本优化**：自动清理和优化文本，使其更适合语音表达
- **灵活配置**：支持自定义参考音频、文本和模型权重

## 快速开始

### 1. 前置要求

- Python 3.7+
- 已部署并运行的 GPT-SoVITS 服务（默认地址：http://127.0.0.1:9880）
- MaiBot 核心版本 0.9.0 或更高

### 2. 安装依赖

插件会自动检查并提示安装所需的 Python 依赖：
```bash
pip install aiohttp
```

### 3. 配置插件

首次运行时，插件会自动生成 `config.toml` 配置文件。根据需要修改配置：

```toml
[tts]
server = "http://127.0.0.1:9880"  # GPT-SoVITS 服务地址
timeout = 60                       # 请求超时时间（秒）
max_text_length = 1000             # 最大文本长度

[tts_styles.default]
refer_wav = "参考音频.wav"         # 参考音频文件路径
prompt_text = "参考音频的文本内容"  # 参考音频对应的文本
prompt_language = "zh"             # 参考音频语言（zh/en/ja）
```

## 使用方法

### 关键词触发

在对话中使用以下关键词，MaiBot 会自动判断是否使用语音回复：

- 中文：`语音`、`说话`、`朗读`、`念一下`、`读出来`、`语音回复`、`用语音说`
- 英文：`voice`、`speak`、`tts`

**示例对话：**
```
用户：请用语音说一下今天的天气
麦麦：[发送语音消息]
```

## 配置说明

### 基本配置

```toml
[plugin]
enabled = true              # 是否启用插件
config_version = "2.0.0"    # 配置文件版本

[components]
action_enabled = true       # 是否启用 Action 组件
```

### TTS 服务配置

```toml
[tts]
server = "http://127.0.0.1:9880"  # GPT-SoVITS 服务地址
timeout = 60                       # 请求超时时间（秒）
max_text_length = 1000             # 最大文本长度（字符）
```

### 语音风格配置

可以配置多种语音风格，每种风格使用不同的参考音频和模型：

```toml
# 默认风格
[tts_styles.default]
refer_wav = "神子.wav"
prompt_text = "在这姑且属于人类的社会里，我也不过凭自己兴趣照做而已"
prompt_language = "zh"
gpt_weights = ""        # 可选：GPT 模型权重路径
sovits_weights = ""     # 可选：SoVITS 模型权重路径

# 温柔风格
[tts_styles.温柔]
refer_wav = "温柔.wav"
prompt_text = "温柔的参考文本"
prompt_language = "zh"

# 活泼风格
[tts_styles.活泼]
refer_wav = "活泼.wav"
prompt_text = "活泼的参考文本"
prompt_language = "zh"
```

## 工作原理

1. **触发检测**：检测用户消息中是否包含语音相关关键词
2. **文本处理**：清理特殊字符，优化网络用语（如 `www` → `哈哈哈`）
3. **语言识别**：自动检测文本语言（中文/英文/日文）
4. **风格选择**：根据配置选择合适的语音风格
5. **语音合成**：调用 GPT-SoVITS API 生成语音文件
6. **发送语音**：将生成的语音文件发送给用户

## 文本处理规则

插件会自动优化文本，使其更适合语音表达：

- **移除特殊字符**：保留中日英文、数字和常用标点
- **网络用语转换**：
  - `www` → `哈哈哈`
  - `hhh` → `哈哈`
  - `233` → `哈哈`
  - `666` → `厉害`
  - `88` → `拜拜`
- **长度限制**：超过最大长度的文本会被截断

## 常见问题

### 1. 语音合成失败

**可能原因：**
- GPT-SoVITS 服务未启动或无法访问
- 配置的服务地址不正确
- 参考音频文件路径错误

**解决方法：**
- 确认 GPT-SoVITS 服务正在运行
- 检查 `config.toml` 中的 `server` 地址
- 确认参考音频文件存在且路径正确

### 2. 语音合成超时

**解决方法：**
- 增加 `timeout` 配置值
- 检查网络连接
- 减少文本长度

### 3. 语音效果不理想

**解决方法：**
- 更换质量更好的参考音频
- 调整参考文本，使其与目标语音风格匹配
- 尝试不同的语音风格配置

### 4. 如何添加新的语音风格

在 `config.toml` 中添加新的风格配置：

```toml
[tts_styles.新风格名称]
refer_wav = "新参考音频.wav"
prompt_text = "新参考文本"
prompt_language = "zh"
```

## 技术细节

### API 接口

插件通过 HTTP POST 请求调用 GPT-SoVITS API：

- **端点**：`{server}/tts`
- **方法**：POST
- **Content-Type**：application/json

**请求参数：**
```json
{
  "text": "要转换的文本",
  "text_lang": "zh",
  "ref_audio_path": "参考音频路径",
  "prompt_text": "参考文本",
  "prompt_lang": "zh"
}
```

### 日志输出

插件使用标准的日志系统，可以通过日志查看详细的运行信息：

```
[tts_voice_plugin] 开始GPT-SoVITS语音合成，文本：你好世界..., 风格：default
[tts_voice_plugin] GPT-SoVITS语音发送成功
```

## 开发与贡献

欢迎提交 Issue 和 Pull Request！

### 项目结构

```
tts_voice_plugin/
├── plugin.py          # 插件主代码
├── config.toml        # 配置文件
├── _manifest.json     # 插件元信息
└── README.md          # 文档（本文件）
```

### 依赖信息

- **Python 版本**：3.7+
- **Python 包**：aiohttp
- **外部服务**：GPT-SoVITS

## 版本信息

- **当前版本**：2.0.0
- **作者**：靓仔
- **许可证**：AGPL-3.0
- **项目地址**：https://github.com/xuqian13/tts_voice_plugin

## 许可证

本项目采用 AGPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。

---

**提示**：使用本插件前，请确保已正确部署 GPT-SoVITS 服务并配置好模型文件。
