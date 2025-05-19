import os
import base64
import sys # Import sys
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from openai import OpenAI
import pprint

# 开发环境直接使用脚本所在目录
application_path = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(application_path, '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print(f"SUCCESS: .env file found at {dotenv_path}")
    print(f"Environment variables loaded: {os.environ.get('SILICONFLOW_API_KEY') and 'SILICONFLOW_API_KEY exists' or 'MISSING'} | BASE_URL: {os.environ.get('SILICONFLOW_BASE_URL')}")
    print(f"Loaded .env from: {dotenv_path}")
else:
    print(f"FAILURE: .env file NOT found at {dotenv_path}. Checking current working directory as a fallback.")
    # Fallback for development: load .env from current working directory if not found with script/executable
    # This is often where you run `python app.py` or `flask run` from.
    dotenv_path_cwd = os.path.join(os.getcwd(), '.env')
    if os.path.exists(dotenv_path_cwd):
        load_dotenv(dotenv_path_cwd)
        dotenv_path = dotenv_path_cwd # Update dotenv_path to the one actually used
        print(f"SUCCESS: .env file found and loaded from current working directory: {dotenv_path}")
        print(f"Environment variables loaded: {os.environ.get('SILICONFLOW_API_KEY') and 'SILICONFLOW_API_KEY exists' or 'MISSING'} | BASE_URL: {os.environ.get('SILICONFLOW_BASE_URL')}")
    else:
        print(f"FAILURE: .env file also NOT found in current working directory: {dotenv_path_cwd}")
        print("Current environment keys:", os.environ.keys())
        dotenv_path = None # Indicate .env was not loaded

# --- Debugging Environment Variables (Post-Load Attempt) ---
print("--- Debugging Environment Variables (Post-Load Attempt) ---")
if dotenv_path:
    print(f"Final .env path considered for loading: {dotenv_path}")
    print(f"Does .env exist at that final path? {os.path.exists(dotenv_path)}")
else:
    print(".env file was not found or loaded.")

api_key_debug = os.getenv("SILICONFLOW_API_KEY")
if api_key_debug:
    print(f"SUCCESS: SILICONFLOW_API_KEY found by os.getenv(): '{api_key_debug[:5]}...' (partially hidden)")
else:
    print(f"FAILURE: SILICONFLOW_API_KEY was NOT found by os.getenv(). Check .env content and loading logic.")

print(f"Value of SILICONFLOW_BASE_URL: {os.getenv('SILICONFLOW_BASE_URL')}")
print(f"[ENV_CHECK] 文本模型: {os.getenv('SILICONFLOW_MODEL_NAME') or '未配置'}")
print(f"[ENV_CHECK] 视觉模型: {os.getenv('SILICONFLOW_VLM_MODEL_NAME') or '未配置'}")
print("--- End of Debugging ---")

app = Flask(__name__)
app.debug = False # Explicitly set debug to False BEFORE app.run

# Configure SiliconFlow API details from environment variables
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

# Get model names from .env
# SILICONFLOW_MODEL_NAME = os.getenv("SILICONFLOW_MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct") # Old way
SILICONFLOW_TEXT_MODEL = os.getenv("SILICONFLOW_MODEL_NAME")
SILICONFLOW_VLM_MODEL = os.getenv("SILICONFLOW_VLM_MODEL_NAME")

# 添加一个变量来标识当前模型是否是VLM，您需要根据实际情况设置
# 例如，您可以从环境变量读取，或者硬编码一个列表进行检查
IS_CURRENT_MODEL_VLM = False # 假设默认不是VLM，或者根据模型名称判断
# 您可以根据 SILICONFLOW_MODEL_NAME 的值来设置 IS_CURRENT_MODEL_VLM
# 例如： if "vision" in SILICONFLOW_MODEL_NAME.lower() or "vlm" in SILICONFLOW_MODEL_NAME.lower():
# IS_CURRENT_MODEL_VLM = True

# Global variable to hold the OpenAI client instance
client = None

# Function to initialize the OpenAI client
def get_openai_client(model_to_use):
    global client
    
    # 强制环境变量校验
    required_env_vars = [
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_BASE_URL",
        "SILICONFLOW_MODEL_NAME",
        "SILICONFLOW_VLM_MODEL_NAME"
    ]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"缺少必要环境变量: {', '.join(missing_vars)}")

    # 环境变量详细校验
    print("\n=== 环境变量校验开始 ===")
    api_key = os.getenv("SILICONFLOW_API_KEY")
    base_url = os.getenv("SILICONFLOW_BASE_URL")
    text_model = os.getenv("SILICONFLOW_MODEL_NAME")

    print(f"SILICONFLOW_API_KEY存在: {'是' if api_key else '否'}")
    print(f"SILICONFLOW_BASE_URL存在: {'是' if base_url else '否'}")
    print(f"文本模型配置: {text_model or '未配置'}")
    vlm_model = os.getenv("SILICONFLOW_VLM_MODEL_NAME")
    print(f"VLM模型配置: {vlm_model or '未配置'}")

    if not all([api_key, base_url, text_model, vlm_model]):
        # 移除错误返回语句以保证后续逻辑执行
        pass
        missing = [var for var, val in [
            ('SILICONFLOW_API_KEY', api_key),
            ('SILICONFLOW_BASE_URL', base_url),
            ('SILICONFLOW_MODEL_NAME', text_model),
            ('SILICONFLOW_VLM_MODEL_NAME', vlm_model)
        ] if not val]
        print(f"错误: 缺失必要环境变量 - {', '.join(missing)}")
        return None
    print("=== 环境变量校验通过 ===\n")
    if not model_to_use:
        print("Error: No model specified for the client.") # Should not happen based on logic
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        # Test connectivity or model validity (optional, model specific)
        # client.models.retrieve(model_to_use) # This can be used to check if model exists
        print(f"OpenAI client initialized with API Key: {api_key[:5]}..., Base URL: {base_url}, Model: {model_to_use}")
        return client
    except Exception as e:
        print(f"Error initializing OpenAI client: {e}")
        return None

def generate_prompt_for_test_cases(requirement_text=None, image_data_url=None):
    """
    Generates a prompt for the LLM to create test cases.
    This is a placeholder and needs to be refined based on the specific model's capabilities.
    """
    prompt_parts = []
    if requirement_text:
        prompt_parts.append(f"Requirement Text:\n{requirement_text}")
    
    # For image input, the OpenAI client typically expects messages in a specific format
    # with type "image_url" and the image data.
    # This function currently just describes that an image was provided for the text prompt.
    # Actual image sending will require a model that supports multimodal inputs via the OpenAI SDK.
    if image_data_url:
         prompt_parts.append("An image has been provided as part of the requirements. Please analyze it along with any text.")
    
    if not prompt_parts:
        return None

    full_requirement_description = "\n\n".join(prompt_parts)
    
    return f"""Analyze the following software requirements and generate comprehensive test cases.
For each test case, include:
- Test Case ID (e.g., TC_001)
- Test Case Description
- Preconditions
- Test Steps (numbered)
- Expected Results
- Priority (High, Medium, Low)

Requirements:
{full_requirement_description}

Generate the test cases based on these requirements.
If an image was mentioned, consider its content as part of the requirements.
"""

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate-test-cases', methods=['POST'])
def generate_test_cases():
    global client
    # 环境变量预校验
    required_vars = ["SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "SILICONFLOW_MODEL_NAME", "SILICONFLOW_VLM_MODEL_NAME"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        return jsonify({"error": f"缺少必要环境变量: {', '.join(missing_vars)}"}), 500
    
    # 初始化全局client
    get_openai_client(SILICONFLOW_TEXT_MODEL)
    
    if not client and not os.getenv("ALLOW_MOCK_API"):
        return jsonify({"error": "API 客户端未配置。缺少 SILICONFLOW_API_KEY。"}), 500
    
    requirement_text = request.form.get('requirement_text')
    requirement_image_file = request.files.get('requirement_image')
    
    # 模型选择逻辑
    chosen_model = os.getenv('SILICONFLOW_MODEL_NAME')
    if requirement_image_file:
        chosen_model = os.getenv('SILICONFLOW_VLM_MODEL_NAME')
        print(f"[MODEL_SELECTION] 检测到图片输入，选择VLM模型: {chosen_model}")
    else:
        print(f"[MODEL_SELECTION] 使用默认文本模型: {chosen_model}")
    
    if not chosen_model:
        print("[ERROR] 未配置模型环境变量")
        return jsonify({"error": "服务器模型配置错误"}), 500
    
    print(f"[ENV_VALIDATION] 文本模型配置有效性: {os.getenv('SILICONFLOW_MODEL_NAME') is not None}")
    print(f"[ENV_VALIDATION] VLM模型配置有效性: {os.getenv('SILICONFLOW_VLM_MODEL_NAME') is not None}")
    if not requirement_text and not requirement_image_file: # This check might be redundant if relying on chosen_model
        return jsonify({"error": "请提供需求文本或需求图片。"}), 400
    
    # 最终模型验证（冗余检查）
    if not chosen_model: 
        return jsonify({"error": "无法确定要使用的模型。"}), 500

    # --- Actual API Call (or mock) ---
    try:
        # This prompt needs to be adapted based on whether it's text, image, or multimodal.
        # And the model chosen must support the input type.
        
        messages = []
        content_parts = []

        if requirement_text:
            content_parts.append({"type": "text", "text": requirement_text})

        # 添加图片数据URL生成逻辑
        if requirement_image_file:
            try:
                # 获取文件扩展名
                file_ext = requirement_image_file.filename.split('.')[-1].lower()
                if file_ext not in ['jpg', 'jpeg', 'png', 'gif']:
                    return jsonify({"error": "不支持的图片格式。请使用 JPG, JPEG, PNG 或 GIF 格式。"}), 400

                # 检查文件大小（限制为5MB）
                image_data = requirement_image_file.read()
                if len(image_data) > 5 * 1024 * 1024:
                    return jsonify({"error": "图片大小超过限制（最大5MB）"}), 400

                # 生成base64编码的图片URL
                image_data_url = f"data:image/{file_ext};base64,{base64.b64encode(image_data).decode('utf-8')}"
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": image_data_url, "detail": "high"}
                })
                print(f"成功处理图片: {requirement_image_file.filename}, 大小: {len(image_data)/1024:.2f}KB")
            except Exception as e:
                print(f"处理图片时发生错误: {str(e)}")
                return jsonify({"error": f"处理图片时发生错误: {str(e)}"}), 500
        
        if not content_parts:
             return jsonify({"error": "No content to process."}), 400

        # Construct the main instruction prompt for test case generation
        instruction_prompt = """请根据提供的软件需求（文本和/或图片）生成全面的测试用例。
每个测试用例必须包含以下内容：
- 测试用例编号（例如：TC_001）
- 测试用例描述
- 前置条件
- 测试步骤（请用数字编号）
- 预期结果
- 优先级（高、中、低）

请确保：
1. 所有内容使用中文
2. 测试步骤清晰明确，每个步骤都是可执行的
3. 预期结果要具体且可验证
4. 优先级要根据功能重要性和影响范围来判定

请基于以下需求生成测试用例："""
        
        messages.append({"role": "system", "content": "你是一位专业的QA工程师，擅长从需求文档中提取关键信息并生成高质量的测试用例。请确保生成的测试用例全面、准确且易于执行。"})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": instruction_prompt}
            ] + content_parts # Add the actual requirements (text/image) after the instruction
        })

        # 调试：打印messages内容，检查图片和文本是否正确传递
        print("[DEBUG] 即将发送给API的messages内容：")
        pprint.pprint(messages)

        if not client or not chosen_model: # Mock response if API key is not set
            print("Mocking SiliconFlow API call...")
            mock_test_cases = """
测试用例编号：TC_001
测试用例描述：验证用户使用有效凭据登录系统
前置条件：
1. 系统中已存在有效的用户账号
2. 用户能够访问登录页面

测试步骤：
1. 打开系统登录页面
2. 在用户名输入框中输入有效的用户名
3. 在密码输入框中输入对应的有效密码
4. 点击"登录"按钮

预期结果：
1. 系统成功验证用户凭据
2. 用户被重定向到系统主页
3. 页面顶部显示用户名称
4. 登录状态保持有效

优先级：高

测试用例编号：TC_002
测试用例描述：验证用户使用无效凭据登录系统
前置条件：
1. 用户能够访问登录页面

测试步骤：
1. 打开系统登录页面
2. 在用户名输入框中输入无效的用户名
3. 在密码输入框中输入无效的密码
4. 点击"登录"按钮

预期结果：
1. 系统显示错误提示信息："用户名或密码错误"
2. 用户停留在登录页面
3. 密码输入框被清空
4. 用户名输入框内容保持不变

优先级：中
"""
            if requirement_image_file:
                # 临时保存文件验证
                temp_path = os.path.join('uploads', requirement_image_file.filename)
                requirement_image_file.save(temp_path)
                print(f"[DEBUG] 文件已临时保存到: {temp_path}")
                mock_test_cases += f"\n(Image '{requirement_image_file.filename}' was processed - mock response)"
            
            return jsonify({"test_cases": mock_test_cases})

        # Real API call
        completion = client.chat.completions.create(
            model=chosen_model,
            messages=messages,
            max_tokens=2000,
            temperature=0.5
        )
        print("[DEBUG] API返回内容：")
        pprint.pprint(completion)
        generated_text = completion.choices[0].message.content
        return jsonify({"test_cases": generated_text.strip()})

    except Exception as e:
        error_message = str(e)
        if "rate_limit" in error_message.lower():
            return jsonify({"error": "API调用频率超限，请稍后重试"}), 429
        elif "timeout" in error_message.lower():
            return jsonify({"error": "API请求超时，请检查网络连接后重试"}), 504
        elif "authentication" in error_message.lower():
            return jsonify({"error": "API认证失败，请检查API密钥是否正确"}), 401
        elif "model_not_found" in error_message.lower():
            return jsonify({"error": "指定的模型不存在或未授权使用"}), 400
        elif "context_length_exceeded" in error_message.lower():
            return jsonify({"error": "输入内容过长，请减少文本或图片大小"}), 400
        else:
            app.logger.error(f"调用SiliconFlow API时发生错误: {e}", exc_info=True)
            return jsonify({"error": f"生成测试用例时发生错误: {error_message}"}), 500

if __name__ == '__main__':
    # Make sure to use a production-ready WSGI server for actual deployment
    # For PyInstaller, debug=False and use_reloader=False are important
    print("Starting Flask application...")
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)