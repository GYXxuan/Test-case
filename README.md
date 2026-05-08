# 测试用例生成器

一个基于大模型 API 的测试用例自动生成工具（Flask Web 应用）。支持文本和图片输入，可接入任意 OpenAI 兼容接口的文本模型和视觉模型，覆盖 10 种经典测试方法，提供流式输出、历史记录和 CSV 导出。

## 功能特性

- **双模型架构**：文本模型和视觉模型各自独立的 API Key / Base URL / 模型名，可混用不同厂商
- **10 种测试方法覆盖**：等价类划分、边界值分析、判定表、正交试验、状态迁移、场景法、错误猜测、探索性测试、异常测试、正向/反向用例
- **文本 + 图片输入**：支持纯文本、纯图片、文本+图片混合输入，多图上传
- **流式输出**：开启后逐字显示生成结果，无需等待完整响应
- **结构化渲染**：测试用例以卡片形式展示，优先级高亮，步骤编号列表
- **CSV 导出**：一键导出，支持 Excel 直接打开（UTF-8 BOM）
- **历史记录**：浏览器本地存储最近 20 条生成记录，支持加载和删除
- **速率限制**：内置 IP 级别频控，防止 API 费用失控
- **Token 用量统计**：每次 API 调用记录 token 消耗和耗时
- **模型选择**：前端支持从配置的白名单模型中选择，上传图片时自动限制为视觉模型
- **健康检查**：`/health` 端点返回服务状态

## 快速开始

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 创建 `.env` 文件

```env
# ── 文本模型 ──
SILICONFLOW_API_KEY=你的文本模型API密钥
SILICONFLOW_BASE_URL=https://api.deepseek.com
SILICONFLOW_MODEL_NAME=deepseek-v4-pro

# ── 视觉模型 ──
SILICONFLOW_VLM_MODEL_NAME=models/gemini-2.5-flash
VLM_API_KEY=你的视觉模型API密钥
VLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

> 视觉模型的 `VLM_API_KEY` 和 `VLM_BASE_URL` 如不配置，会自动回退使用文本模型的配置。

### 3. 启动

```bash
python app.py
```

访问 `http://127.0.0.1:5001`

## 支持的厂商

| 厂商 | Base URL | 文本模型示例 | 视觉模型示例 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-pro` | 不支持视觉 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | `gpt-4o` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | — | `models/gemini-2.5-flash` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `GLM-4.7` | `glm-4v-plus-0111` |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` | `qwen-vl-max` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-72B-Instruct` | `Qwen/Qwen2.5-VL-72B-Instruct` |
| 月之暗面 | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | `kimi-k2.5` |

## 全部环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SILICONFLOW_API_KEY` | — | 文本模型 API 密钥（必填） |
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | 文本模型 API 地址 |
| `SILICONFLOW_MODEL_NAME` | — | 文本模型名（必填） |
| `SILICONFLOW_VLM_MODEL_NAME` | — | 视觉模型名（必填） |
| `VLM_API_KEY` | 回退到文本 Key | 视觉模型 API 密钥 |
| `VLM_BASE_URL` | 回退到文本 URL | 视觉模型 API 地址 |
| `PORT` | `5001` | 服务端口 |
| `SECRET_KEY` | 自动生成 | Flask 密钥 |
| `MAX_TOKENS` | `8192` | 默认输出 token 上限 |
| `MIN_TOKENS` | `256` | 前端 token 下限 |
| `MAX_ALLOWED_TOKENS` | `16384` | 前端 token 上限 |
| `TEMPERATURE` | `0.5` | 默认温度参数 |
| `API_TIMEOUT` | `60` | API 调用超时（秒） |
| `API_MAX_RETRIES` | `3` | API 失败重试次数 |
| `MAX_TEXT_LENGTH` | `10000` | 需求文本最大字符数 |
| `MAX_IMAGE_SIZE_MB` | `5` | 单张图片大小限制（MB） |
| `MAX_IMAGE_COUNT` | `5` | 单次最多上传图片数 |
| `MAX_TOTAL_IMAGE_SIZE_MB` | `15` | 单次图片总大小限制（MB） |
| `MAX_REQUEST_SIZE_MB` | `20` | 请求体总大小限制（MB） |
| `RATE_LIMIT_WINDOW` | `60` | 频控窗口（秒） |
| `RATE_LIMIT_MAX` | `20` | 频控窗口内最大请求数 |
| `AVAILABLE_MODELS` | — | 前端可选模型列表（逗号分隔） |
| `ALLOW_MOCK_API` | 关闭 | 设为 `1` 启用 mock 模式（不调用 API） |
| `COST_SUMMARY_TOKEN` | — | 设置后访问成本统计需要鉴权 |

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 主页面 |
| `/health` | GET | 健康检查，返回各客户端状态 |
| `/api/models` | GET | 返回可用模型列表 |
| `/api/cost-summary` | GET | Token 用量统计 |
| `/generate-test-cases` | POST | 生成测试用例（普通模式） |
| `/generate-test-cases-stream` | POST | 生成测试用例（SSE 流式模式） |

## 测试

```bash
python -m unittest discover -v
```

## Docker

```bash
docker build -t test-case-generator .
docker run -p 5001:5001 --env-file .env test-case-generator
```
