document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('requirementsForm');
    const resultDiv = document.getElementById('testCasesResult');
    const spinner = document.getElementById('spinner');

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        spinner.style.display = 'block';
        resultDiv.textContent = '';

        const formData = new FormData();
        const requirementText = document.getElementById('requirementText').value;
        const requirementImage = document.getElementById('requirementImage').files[0];

        if (requirementText) {
            formData.append('requirement_text', requirementText);
        }
        if (requirementImage) {
            formData.append('requirement_image', requirementImage);
        }

        if (!requirementText && !requirementImage) {
            resultDiv.textContent = '请提供需求文本或需求图片。';
            spinner.style.display = 'none';
            return;
        }

        try {
            const response = await fetch('/generate-test-cases', {
                method: 'POST',
                body: formData, // FormData will set the correct Content-Type (multipart/form-data)
            });

            spinner.style.display = 'none';
            if (response.ok) {
                const data = await response.json();
                if (data.test_cases) {
                    resultDiv.textContent = data.test_cases;
                } else if (data.error) {
                    resultDiv.textContent = `错误：${data.error}`;
                }
            } else {
                const errorData = await response.json();
                resultDiv.textContent = `错误：${errorData.error || response.statusText}`;
            }
        } catch (error) {
            spinner.style.display = 'none';
            console.error('提交表单时出错：', error);
            resultDiv.textContent = '发生意外错误，请检查控制台。';
        }
    });
}); 