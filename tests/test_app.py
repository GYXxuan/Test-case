import io
import json
import os
import sys
import unittest

from werkzeug.datastructures import FileStorage


# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test env vars before importing app
os.environ["SILICONFLOW_API_KEY"] = "test-key"
os.environ["SILICONFLOW_BASE_URL"] = "https://test.api.com/v1"
os.environ["SILICONFLOW_MODEL_NAME"] = "test-model"
os.environ["SILICONFLOW_VLM_MODEL_NAME"] = "test-vlm-model"
os.environ["VLM_API_KEY"] = "test-vlm-key"
os.environ["VLM_BASE_URL"] = "https://test-vlm.api.com/v1"
os.environ["AVAILABLE_MODELS"] = "test-model,test-vlm-model"
os.environ["ALLOW_MOCK_API"] = "1"
os.environ.pop("COST_SUMMARY_TOKEN", None)

from app import (  # noqa: E402
    app,
    _build_messages,
    _check_rate_limit,
    _classify_error,
    _process_images,
    _rate_store,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class TestRateLimit(unittest.TestCase):
    def setUp(self):
        _rate_store.clear()

    def test_allows_first_request(self):
        self.assertTrue(_check_rate_limit("test-ip-1"))

    def test_blocks_after_limit(self):
        ip = "test-ip-2"
        for _ in range(20):
            _check_rate_limit(ip)
        self.assertFalse(_check_rate_limit(ip))


class TestImageProcessing(unittest.TestCase):
    def test_accepts_valid_png(self):
        file_storage = FileStorage(stream=io.BytesIO(PNG_BYTES), filename="requirement.png")
        parts = _process_images([file_storage])
        self.assertEqual(len(parts), 1)
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_rejects_extension_mismatch(self):
        file_storage = FileStorage(stream=io.BytesIO(b"not-a-png"), filename="requirement.png")
        with self.assertRaisesRegex(ValueError, "内容与扩展名不匹配"):
            _process_images([file_storage])

    def test_rejects_unsupported_extension(self):
        file_storage = FileStorage(stream=io.BytesIO(b"abc"), filename="requirement.txt")
        with self.assertRaisesRegex(ValueError, "不支持图片格式"):
            _process_images([file_storage])

    def test_image_messages_include_visual_grounding_instruction(self):
        file_storage = FileStorage(stream=io.BytesIO(PNG_BYTES), filename="requirement.png")
        messages = _build_messages("用户补充说明", [file_storage])
        user_content = messages[1]["content"]
        self.assertIn("忽略旧结果", user_content[1]["text"])
        self.assertEqual(user_content[2]["type"], "text")
        self.assertEqual(user_content[3]["type"], "image_url")


class TestErrorClassification(unittest.TestCase):
    def test_rate_limit_error(self):
        _msg, code = _classify_error(Exception("rate_limit exceeded"))
        self.assertEqual(code, 429)

    def test_timeout_error(self):
        _msg, code = _classify_error(Exception("Request timeout"))
        self.assertEqual(code, 504)

    def test_auth_error(self):
        _msg, code = _classify_error(Exception("authentication failed 401"))
        self.assertEqual(code, 401)

    def test_model_not_found(self):
        _msg, code = _classify_error(Exception("model_not_found"))
        self.assertEqual(code, 400)

    def test_context_length(self):
        _msg, code = _classify_error(Exception("context_length_exceeded"))
        self.assertEqual(code, 400)

    def test_generic_error(self):
        _msg, code = _classify_error(Exception("something else"))
        self.assertEqual(code, 500)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        _rate_store.clear()
        self.client = app.test_client()

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("测试用例".encode("utf-8"), resp.data)

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("status", data)
        self.assertTrue(data["mock_api"])

    def test_models_endpoint(self):
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("models", data)
        self.assertIn("test-model", data["models"])

    def test_generate_no_input(self):
        resp = self.client.post("/generate-test-cases", data={})
        self.assertEqual(resp.status_code, 400)

    def test_generate_mock_returns_structured_payload(self):
        resp = self.client.post("/generate-test-cases", data={
            "requirement_text": "用户登录功能需求"
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("test_cases", data)
        self.assertIn("test_cases_data", data)
        self.assertEqual(data["test_cases_data"]["test_cases"][0]["id"], "TC_001")
        self.assertIn("source_evidence", data["test_cases_data"]["test_cases"][0])

    def test_text_too_long(self):
        resp = self.client.post("/generate-test-cases", data={
            "requirement_text": "x" * 20000
        })
        self.assertEqual(resp.status_code, 400)

    def test_invalid_max_tokens_returns_400(self):
        resp = self.client.post("/generate-test-cases", data={
            "requirement_text": "用户登录功能需求",
            "max_tokens": "abc",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Max Tokens", resp.get_json()["error"])

    def test_invalid_temperature_returns_400_for_stream(self):
        resp = self.client.post("/generate-test-cases-stream", data={
            "requirement_text": "用户登录功能需求",
            "temperature": "bad",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Temperature", resp.get_json()["error"])

    def test_model_override_must_be_allowed(self):
        resp = self.client.post("/generate-test-cases", data={
            "requirement_text": "用户登录功能需求",
            "model": "unknown-model",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("允许列表", resp.get_json()["error"])

    def test_image_upload_rejects_text_model_override(self):
        resp = self.client.post(
            "/generate-test-cases",
            data={
                "model": "test-model",
                "requirement_images": (io.BytesIO(PNG_BYTES), "requirement.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("视觉模型", resp.get_json()["error"])

    def test_invalid_image_upload_returns_400(self):
        resp = self.client.post(
            "/generate-test-cases",
            data={"requirement_images": (io.BytesIO(b"not-a-png"), "requirement.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("内容与扩展名不匹配", resp.get_json()["error"])

    def test_valid_image_upload_uses_mock_payload(self):
        resp = self.client.post(
            "/generate-test-cases",
            data={"requirement_images": (io.BytesIO(PNG_BYTES), "requirement.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("test_cases_data", data)

    def test_stream_mock_emits_sse(self):
        resp = self.client.post("/generate-test-cases-stream", data={
            "requirement_text": "用户登录功能需求"
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode("utf-8")
        self.assertIn("data:", body)
        self.assertIn("[DONE]", body)

    def test_cost_summary_empty_or_existing(self):
        resp = self.client.get("/api/cost-summary")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("total_calls", resp.get_json())


if __name__ == "__main__":
    unittest.main()
