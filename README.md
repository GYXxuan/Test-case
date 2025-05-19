# 硅基流动 API 测试用例生成器

一个通过调用硅基流动 (SiliconFlow) API 来生成测试用例文档的 Web 应用程序。可以上传需求图片或输入需求文本。

## 功能特性

- 上传需求图片
- 输入需求文本
- 调用硅基流动 API 处理需求
- 生成并显示测试用例

## 安装与设置

1.  **克隆仓库：**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **创建并激活虚拟环境：**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows 系统请使用 `venv\Scripts\activate`
    ```

3.  **安装依赖：**
    ```bash
    pip install -r requirements.txt
    ```

4.  **设置环境变量：**
    在项目根目录下创建一个 `.env` 文件，并添加您的硅基流动 API 密钥：
    ```env
    SILICONFLOW_API_KEY="在此填入您的硅基流动API密钥"
    SILICONFLOW_BASE_URL="https://api.siliconflow.cn/v1" 
    # 如果硅基流动文档中的基础 URL 不同，请在此处核对并修改
    ```
    您还需要从硅基流动选择一个合适的模型用于分析需求和生成测试用例。请在 `.env` 文件中更新 `SILICONFLOW_MODEL_NAME`。
    ```env
    SILICONFLOW_MODEL_NAME="Qwen/Qwen2.5-72B-Instruct" # 示例模型，请选择一个适用于视觉/文本分析和生成的模型
    ```

5.  **运行 Flask 应用：**
    ```bash
    flask run
    ```
    应用程序将在 `http://127.0.0.1:5000` 上可用。

## 如何使用

- 在浏览器中打开网站。
- 可以选择上传图片，或在文本框中输入您的需求。
- 点击“生成测试用例”按钮。
- 生成的测试用例将显示在表单下方。 
