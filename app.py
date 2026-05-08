import base64
import json
import logging
import os
import threading
import time
from collections import defaultdict

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from openai import OpenAI
from werkzeug.exceptions import RequestEntityTooLarge


# ── Logging ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── Load .env ────────────────────────────────────────────
application_path = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(application_path, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    logger.info(".env loaded from script directory: %s", dotenv_path)
else:
    dotenv_path_cwd = os.path.join(os.getcwd(), ".env")
    if os.path.exists(dotenv_path_cwd):
        load_dotenv(dotenv_path_cwd)
        logger.info(".env loaded from current working directory: %s", dotenv_path_cwd)
    else:
        logger.warning(".env file not found")


# ── Settings ─────────────────────────────────────────────
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "3"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))
MIN_TOKENS = int(os.getenv("MIN_TOKENS", "256"))
MAX_ALLOWED_TOKENS = int(os.getenv("MAX_ALLOWED_TOKENS", "16384"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.5"))
MIN_TEMPERATURE = float(os.getenv("MIN_TEMPERATURE", "0"))
MAX_TEMPERATURE = float(os.getenv("MAX_TEMPERATURE", "2"))
PORT = int(os.getenv("PORT", "5001"))
ALLOWED_IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE_MB", "5")) * 1024 * 1024
MAX_IMAGE_COUNT = int(os.getenv("MAX_IMAGE_COUNT", "5"))
MAX_TOTAL_IMAGE_SIZE = int(os.getenv("MAX_TOTAL_IMAGE_SIZE_MB", "15")) * 1024 * 1024
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "10000"))
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE_MB", "20")) * 1024 * 1024
COST_SUMMARY_TOKEN = os.getenv("COST_SUMMARY_TOKEN")


# ── App & Security Config ────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_SIZE


# ── API Config ───────────────────────────────────────────
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_TEXT_MODEL = os.getenv("SILICONFLOW_MODEL_NAME")
SILICONFLOW_VLM_MODEL = os.getenv("SILICONFLOW_VLM_MODEL_NAME")

VLM_API_KEY = os.getenv("VLM_API_KEY") or SILICONFLOW_API_KEY
VLM_BASE_URL = os.getenv("VLM_BASE_URL") or SILICONFLOW_BASE_URL

logger.info("文本模型: %s", SILICONFLOW_TEXT_MODEL or "未配置")
logger.info("视觉模型: %s", SILICONFLOW_VLM_MODEL or "未配置")


# ── Available Models (exposed to frontend) ──────────────
_available_models_raw = os.getenv("AVAILABLE_MODELS", "")
AVAILABLE_MODELS = [m.strip() for m in _available_models_raw.split(",") if m.strip()]
if SILICONFLOW_TEXT_MODEL and SILICONFLOW_TEXT_MODEL not in AVAILABLE_MODELS:
    AVAILABLE_MODELS.insert(0, SILICONFLOW_TEXT_MODEL)
if SILICONFLOW_VLM_MODEL and SILICONFLOW_VLM_MODEL not in AVAILABLE_MODELS:
    AVAILABLE_MODELS.insert(0, SILICONFLOW_VLM_MODEL)


# ── Rate Limiter (in-memory, per-IP) ─────────────────────
_rate_window = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
_rate_max = int(os.getenv("RATE_LIMIT_MAX", "20"))
_rate_store = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(ip):
    now = time.time()
    with _rate_lock:
        bucket = [t for t in _rate_store[ip] if now - t < _rate_window]
        _rate_store[ip] = bucket
        if len(bucket) >= _rate_max:
            return False
        bucket.append(now)
        _rate_store[ip] = bucket
        return True


# ── Cost Tracking ────────────────────────────────────────
_cost_log_path = os.path.join(application_path, "cost_log.jsonl")
_cost_lock = threading.Lock()


def _log_cost(model, prompt_tokens, completion_tokens, duration):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "duration_s": round(duration, 2),
    }
    with _cost_lock:
        try:
            with open(_cost_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("写入cost_log失败: %s", e)


# ── Client Management ────────────────────────────────────
_text_client = None
_vlm_client = None


def _init_client(api_key, base_url, label):
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=API_TIMEOUT)
        logger.info("[%s] client initialized (%s)", label, base_url)
        return client
    except Exception as e:
        logger.error("[%s] client init failed: %s", label, e)
        return None


def get_text_client():
    global _text_client
    if _text_client is None and SILICONFLOW_API_KEY:
        _text_client = _init_client(SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, "text")
    return _text_client


def get_vlm_client():
    global _vlm_client
    if _vlm_client is None and VLM_API_KEY:
        _vlm_client = _init_client(VLM_API_KEY, VLM_BASE_URL, "vlm")
    return _vlm_client


# ── Prompt Template ──────────────────────────────────────
INSTRUCTION_PROMPT = """请根据提供的软件需求（文本和/或图片）生成全面、可执行、可验证的测试用例。

每个测试用例请严格按以下格式输出，不要输出任何额外的说明文字：

测试用例编号：TC_001
测试用例描述：（描述测试目的）
测试方法：（从以下方法中选择，可多个用分号分隔）
类型：（正向/反向/边界/异常/安全/兼容性/性能/可用性）
需求追踪：（对应的需求点或页面元素）
来源证据：（来自需求文本或图片中的原始证据）
前置条件：
1. 前置条件1
2. 前置条件2
测试步骤：
1. 步骤1
2. 步骤2
预期结果：
1. 预期结果1
2. 预期结果2
优先级：（高/中/低）

生成要求：
1. 所有内容使用中文。
2. 测试步骤必须清晰、独立、可执行，不要使用"检查是否正常"等空泛描述。
3. 预期结果必须具体、可验证，与步骤一一对应。
4. 必须系统性地使用以下10种测试方法设计用例，每个用例标明所用方法：
   - 有效等价类：将有效输入划分类别，每个有效类至少一个用例
   - 无效等价类：将无效/非法/异常输入划分类别，每类至少一个用例
   - 边界值分析：对数值/长度/时间/容量等有界输入，覆盖边界、边界±1、边界±典型偏差
   - 判定表/因果图：分析条件组合和动作结果，整理判定表，每条规则至少一个用例
   - 正交试验法：多独立参数时用正交表减少组合，关键交互全覆盖
   - 状态迁移测试：识别系统状态和事件，覆盖所有合法迁移及至少一条非法迁移
   - 场景法：根据业务流程构建端到端场景，覆盖主流程、备选流程和异常流程
   - 错误猜测法：基于测试经验推断易错点，设计针对性用例
   - 探索性测试：给出探索章程（Charter），含目标、区域、时间盒、关注点
   - 异常测试：覆盖网络中断、超时、资源不足、并发冲突等异常场景
5. 至少产出10个用例，至少覆盖6种方法，一种方法可以对应多个用例。
6. 优先级只能使用"高""中""低"，根据业务影响和失败后果判定。
7. 如果需求存在歧义，请以"风险提示："开头在末尾说明，不要自行臆造关键业务规则。
8. 所有用例输出完毕后，以"测试方法覆盖："开头，列出实际使用的方法及未使用方法的原因。

图片分析规则：
1. 如果上传了图片，必须先基于图片可见内容提取测试点；需求文本只作为补充说明。
2. 每个测试用例必须在"来源证据"中写出可追溯证据，来自图片可见文字/控件/布局或用户输入的需求文本。
3. 如果图片是本工具页面截图，包含"生成的测试用例""测试用例编号"等旧输出区域，必须忽略这些旧输出，不要把旧输出再次当成需求。
4. 如果图片和文本冲突，以图片中"需求文本/需求图片/表单输入区域/业务页面主体"的内容为准，并把冲突写入"风险提示"。
5. 禁止生成与图片和文本都无关的通用模板用例；无法从图片识别出业务含义时，围绕可见元素生成有限用例，并在风险提示中说明需要补充需求。

请基于以下需求生成测试用例："""

SYSTEM_PROMPT = "你是一位资深软件测试工程师，擅长从需求文档、页面截图和业务描述中提取可验证测试点，并输出结构化、高质量、可回归的测试用例。"


# ── Helpers ──────────────────────────────────────────────
_IMAGE_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}
_IMAGE_KIND_BY_EXT = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}


def _allow_mock_api():
    return os.getenv("ALLOW_MOCK_API", "").lower() in {"1", "true", "yes", "on"}


def _detect_image_kind(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _process_images(files):
    """Validate and encode uploaded images. Returns list of content_part dicts."""
    if len(files) > MAX_IMAGE_COUNT:
        raise ValueError(f"最多只能上传{MAX_IMAGE_COUNT}张图片")

    parts = []
    total_size = 0
    for f in files:
        if not f or not f.filename:
            continue
        if "." not in f.filename:
            raise ValueError(f"图片 {f.filename} 缺少文件扩展名")

        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"不支持图片格式: {ext}")

        data = f.read()
        if not data:
            raise ValueError(f"图片 {f.filename} 为空")
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError(f"图片 {f.filename} 超过{MAX_IMAGE_SIZE // 1024 // 1024}MB限制")

        total_size += len(data)
        if total_size > MAX_TOTAL_IMAGE_SIZE:
            raise ValueError(f"图片总大小超过{MAX_TOTAL_IMAGE_SIZE // 1024 // 1024}MB限制")

        detected_kind = _detect_image_kind(data)
        expected_kind = _IMAGE_KIND_BY_EXT[ext]
        if detected_kind != expected_kind:
            raise ValueError(f"图片 {f.filename} 内容与扩展名不匹配或不是有效图片")

        b64 = base64.b64encode(data).decode("utf-8")
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{_IMAGE_MIME_BY_EXT[ext]};base64,{b64}"},
        })
        logger.info("图片处理成功: %s (%.1fKB)", f.filename, len(data) / 1024)
    return parts


def _call_api_with_retry(client, **kwargs):
    last_error = None
    for attempt in range(API_MAX_RETRIES):
        try:
            return client.chat.completions.create(**kwargs, timeout=API_TIMEOUT)
        except Exception as e:
            last_error = e
            if attempt >= API_MAX_RETRIES - 1:
                break
            msg = str(e).lower()
            if "rate_limit" in msg or "429" in msg:
                delay = min(30 * (attempt + 1), 90)
                logger.warning("API限流(429), 第%d次重试, 等待%ds", attempt + 1, delay)
            else:
                delay = 2 ** attempt
                logger.warning("API retry %d/%d, waiting %ds: %s", attempt + 1, API_MAX_RETRIES, delay, e)
            time.sleep(delay)
    raise last_error


def _classify_error(e):
    msg = str(e)
    msg_lower = msg.lower()
    if "rate_limit" in msg_lower or "429" in msg:
        return "API调用频率超限，请稍后重试", 429
    if "timeout" in msg_lower:
        return "API请求超时，请检查网络连接后重试", 504
    if "authentication" in msg_lower or "401" in msg:
        return "API认证失败，请检查API密钥是否正确", 401
    if "model_not_found" in msg_lower:
        return "指定的模型不存在或未授权使用", 400
    if "context_length" in msg_lower:
        return "输入内容过长，请减少文本或图片大小", 400
    return "生成测试用例时发生错误，请稍后重试", 500


def _parse_int_param(name, default, minimum, maximum, label):
    raw = request.form.get(name, "")
    if raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{label}必须是整数")
    if value < minimum or value > maximum:
        raise ValueError(f"{label}必须在{minimum}到{maximum}之间")
    return value


def _parse_float_param(name, default, minimum, maximum, label):
    raw = request.form.get(name, "")
    if raw == "":
        value = default
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{label}必须是数字")
    if value < minimum or value > maximum:
        raise ValueError(f"{label}必须在{minimum:g}到{maximum:g}之间")
    return value


def _is_vision_model(model):
    model_lower = model.lower()
    return any(kw in model_lower for kw in ["vl", "vision", "4v", "gpt-4o", "gemini", "claude", "glm-4.6v", "glm-4.5v"])


def _is_allowed_vision_override(model):
    return model == SILICONFLOW_VLM_MODEL or _is_vision_model(model)


def _select_model(use_vision):
    override_model = request.form.get("model", "").strip()
    if override_model:
        if override_model not in AVAILABLE_MODELS:
            raise ValueError("所选模型不在服务器允许列表中")
        if use_vision and not _is_allowed_vision_override(override_model):
            raise ValueError("上传图片时必须选择视觉模型，不能使用文本模型")
        client = get_vlm_client() if (use_vision or _is_vision_model(override_model)) else get_text_client()
        return override_model, client

    chosen_model = SILICONFLOW_VLM_MODEL if use_vision else SILICONFLOW_TEXT_MODEL
    client = get_vlm_client() if use_vision else get_text_client()
    return chosen_model, client


def _build_messages(requirement_text, image_files):
    content_parts = []
    if image_files:
        content_parts.append({
            "type": "text",
            "text": (
                "本次请求包含需求图片。请先读取图片中的可见文字、控件、页面结构和业务主体；"
                "如果截图里包含本工具的旧生成结果区域，请忽略旧结果，只依据需求输入区或业务截图主体生成用例。"
            ),
        })
    if requirement_text:
        content_parts.append({"type": "text", "text": f"用户补充需求文本：{requirement_text}"})
    if image_files:
        content_parts.extend(_process_images(image_files))
    if not content_parts:
        raise ValueError("没有可处理的需求内容")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": INSTRUCTION_PROMPT}] + content_parts},
    ]


def _prepare_generation_request():
    requirement_text = request.form.get("requirement_text", "").strip()
    image_files = [f for f in request.files.getlist("requirement_images") if f and f.filename]

    if not requirement_text and not image_files:
        return None, (jsonify({"error": "请提供需求文本或需求图片。"}), 400)
    if len(requirement_text) > MAX_TEXT_LENGTH:
        return None, (jsonify({"error": f"文本长度超过限制（最大{MAX_TEXT_LENGTH}字符）"}), 400)

    try:
        max_tokens = _parse_int_param("max_tokens", MAX_TOKENS, MIN_TOKENS, MAX_ALLOWED_TOKENS, "Max Tokens")
        temperature = _parse_float_param("temperature", TEMPERATURE, MIN_TEMPERATURE, MAX_TEMPERATURE, "Temperature")
        chosen_model, client = _select_model(bool(image_files))
        messages = _build_messages(requirement_text, image_files)
    except ValueError as e:
        return None, (jsonify({"error": str(e)}), 400)

    if not chosen_model:
        return None, (jsonify({"error": "服务器模型配置错误"}), 500)
    if not client and not _allow_mock_api():
        return None, (jsonify({"error": "API 客户端未配置。缺少必要的环境变量。"}), 500)

    payload = {
        "requirement_text": requirement_text,
        "image_count": len(image_files),
        "model": chosen_model,
        "client": client,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return payload, None


def _strip_json_fence(text):
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_test_cases_payload(payload):
    cases = payload.get("test_cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError("JSON缺少test_cases数组")

    normalized_cases = []
    for idx, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            continue
        priority = str(item.get("priority", "中")).strip()
        if priority not in {"高", "中", "低"}:
            priority = "中"
        normalized_cases.append({
            "id": str(item.get("id") or f"TC_{idx:03d}").strip(),
            "description": str(item.get("description") or "").strip(),
            "preconditions": _coerce_list(item.get("preconditions")),
            "steps": _coerce_list(item.get("steps")),
            "expected_results": _coerce_list(item.get("expected_results")),
            "priority": priority,
            "type": str(item.get("type") or "").strip(),
            "method": str(item.get("method") or "").strip(),
            "requirement_trace": str(item.get("requirement_trace") or "").strip(),
            "source_evidence": str(item.get("source_evidence") or "").strip(),
        })

    if not normalized_cases:
        raise ValueError("JSON中没有有效测试用例")

    coverage = payload.get("coverage_summary") if isinstance(payload.get("coverage_summary"), dict) else {}
    method_coverage = coverage.get("method_coverage") if isinstance(coverage.get("method_coverage"), dict) else {}
    return {
        "test_cases": normalized_cases,
        "coverage_summary": {
            "covered_points": _coerce_list(coverage.get("covered_points")),
            "risk_points": _coerce_list(coverage.get("risk_points")),
            "method_coverage": {
                "等价类划分": bool(method_coverage.get("等价类划分", False)),
                "边界值分析": bool(method_coverage.get("边界值分析", False)),
                "判定表": bool(method_coverage.get("判定表", False)),
                "正交试验": bool(method_coverage.get("正交试验", False)),
                "状态迁移": bool(method_coverage.get("状态迁移", False)),
                "场景法": bool(method_coverage.get("场景法", False)),
                "错误猜测": bool(method_coverage.get("错误猜测", False)),
                "探索性测试": bool(method_coverage.get("探索性测试", False)),
                "异常测试": bool(method_coverage.get("异常测试", False)),
            },
        },
    }


def _parse_structured_test_cases(text):
    cleaned = _strip_json_fence(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(cleaned[start:end + 1])
    return _normalize_test_cases_payload(payload)


def _format_test_cases_text(payload):
    lines = []
    for case in payload.get("test_cases", []):
        lines.extend([
            f"测试用例编号：{case['id']}",
            f"测试用例描述：{case['description']}",
            "前置条件：",
        ])
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(case.get("preconditions", []), start=1))
        lines.append("")
        lines.append("测试步骤：")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(case.get("steps", []), start=1))
        lines.append("")
        lines.append("预期结果：")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(case.get("expected_results", []), start=1))
        lines.append("")
        if case.get("type"):
            lines.append(f"类型：{case['type']}")
        if case.get("method"):
            lines.append(f"测试方法：{case['method']}")
        if case.get("requirement_trace"):
            lines.append(f"需求追踪：{case['requirement_trace']}")
        if case.get("source_evidence"):
            lines.append(f"来源证据：{case['source_evidence']}")
        lines.append(f"优先级：{case['priority']}")
        lines.append("")
    return "\n".join(lines).strip()


def _mock_test_cases_data():
    return {
        "test_cases": [
            {
                "id": "TC_001",
                "description": "验证用户使用有效凭据登录系统",
                "preconditions": ["系统中已存在有效的用户账号", "用户能够访问登录页面"],
                "steps": ["打开系统登录页面", "输入有效用户名", "输入对应的有效密码", "点击登录按钮"],
                "expected_results": ["系统成功验证用户凭据", "用户被重定向到系统主页", "页面顶部显示用户名称", "登录状态保持有效"],
                "priority": "高",
                "type": "正向",
                "method": "等价类划分;场景法",
                "requirement_trace": "用户登录功能",
                "source_evidence": "用户登录功能需求",
            },
            {
                "id": "TC_002",
                "description": "验证用户使用无效凭据登录系统",
                "preconditions": ["用户能够访问登录页面"],
                "steps": ["打开系统登录页面", "输入无效用户名", "输入无效密码", "点击登录按钮"],
                "expected_results": ["系统显示明确的登录失败提示", "用户停留在登录页面", "密码输入框被清空", "用户名输入框内容保持不变"],
                "priority": "中",
                "type": "反向",
                "method": "无效等价类;错误猜测",
                "requirement_trace": "用户登录功能",
                "source_evidence": "用户登录功能需求",
            },
        ],
        "coverage_summary": {
            "covered_points": ["有效登录", "无效凭据登录"],
            "risk_points": ["账号锁定策略、验证码策略和密码复杂度规则需结合真实需求补充"],
            "method_coverage": {
                "等价类划分": True,
                "边界值分析": False,
                "判定表": False,
                "正交试验": False,
                "状态迁移": False,
                "场景法": True,
                "错误猜测": True,
                "探索性测试": False,
                "异常测试": False,
            },
        },
    }


def _mock_test_cases():
    return _format_test_cases_text(_mock_test_cases_data())


def _rate_limit_response():
    ip = request.remote_addr or "127.0.0.1"
    if not _check_rate_limit(ip):
        return jsonify({"error": "请求频率过高，请稍后重试"}), 429
    return None


# ── Routes ───────────────────────────────────────────────
@app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(_e):
    return jsonify({"error": f"请求体超过{MAX_REQUEST_SIZE // 1024 // 1024}MB限制"}), 413


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    text_ok = get_text_client() is not None
    vlm_ok = get_vlm_client() is not None
    return jsonify({
        "status": "ok" if (text_ok or vlm_ok or _allow_mock_api()) else "degraded",
        "text_client": text_ok,
        "vlm_client": vlm_ok,
        "mock_api": _allow_mock_api(),
    })


@app.route("/api/models")
def list_models():
    return jsonify({"models": AVAILABLE_MODELS})


@app.route("/api/cost-summary")
def cost_summary():
    if COST_SUMMARY_TOKEN:
        supplied_token = request.headers.get("X-Cost-Token") or request.args.get("token")
        if supplied_token != COST_SUMMARY_TOKEN:
            return jsonify({"error": "无权访问成本统计"}), 403

    if not os.path.exists(_cost_log_path):
        return jsonify({"total_calls": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0})
    entries = []
    try:
        with open(_cost_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        logger.warning("读取cost_log失败: %s", e)
    return jsonify({
        "total_calls": len(entries),
        "total_prompt_tokens": sum(e.get("prompt_tokens", 0) for e in entries),
        "total_completion_tokens": sum(e.get("completion_tokens", 0) for e in entries),
    })


@app.route("/generate-test-cases", methods=["POST"])
def generate_test_cases():
    limited = _rate_limit_response()
    if limited:
        return limited

    payload, error_response = _prepare_generation_request()
    if error_response:
        return error_response

    logger.info(
        "请求: model=%s, text_len=%d, images=%d, max_tokens=%d, temp=%.2f",
        payload["model"], len(payload["requirement_text"]), payload["image_count"],
        payload["max_tokens"], payload["temperature"],
    )

    if _allow_mock_api() or not payload["client"]:
        mock_payload = _mock_test_cases_data()
        return jsonify({"test_cases": _format_test_cases_text(mock_payload), "test_cases_data": mock_payload})

    try:
        t_start = time.time()
        completion = _call_api_with_retry(
            payload["client"],
            model=payload["model"],
            messages=payload["messages"],
            max_tokens=payload["max_tokens"],
            temperature=payload["temperature"],
        )
        duration = time.time() - t_start

        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        _log_cost(payload["model"], prompt_tokens, completion_tokens, duration)

        generated_text = completion.choices[0].message.content.strip()
        response_data = {
            "test_cases": generated_text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "duration_s": round(duration, 2),
            },
        }
        try:
            response_data["test_cases_data"] = _parse_structured_test_cases(generated_text)
        except Exception as e:
            logger.warning("模型输出不是有效结构化JSON，将按原文返回: %s", e)

        logger.info("API成功: model=%s, %d→%d tokens, %.1fs", payload["model"], prompt_tokens, completion_tokens, duration)
        return jsonify(response_data)

    except Exception as e:
        logger.error("API错误: %s", e, exc_info=True)
        msg, code = _classify_error(e)
        return jsonify({"error": msg}), code


@app.route("/generate-test-cases-stream", methods=["POST"])
def generate_test_cases_stream():
    limited = _rate_limit_response()
    if limited:
        return limited

    payload, error_response = _prepare_generation_request()
    if error_response:
        return error_response

    def generate():
        if _allow_mock_api() or not payload["client"]:
            mock_text = json.dumps(_mock_test_cases_data(), ensure_ascii=False, indent=2)
            yield f"data: {json.dumps({'content': mock_text}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            stream = payload["client"].chat.completions.create(
                model=payload["model"],
                messages=payload["messages"],
                max_tokens=payload["max_tokens"],
                temperature=payload["temperature"],
                stream=True,
                timeout=API_TIMEOUT,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield f"data: {json.dumps({'content': delta.content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Stream错误: %s", e, exc_info=True)
            msg, _code = _classify_error(e)
            yield f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Main ─────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
