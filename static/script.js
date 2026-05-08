// ── Constants ──────────────────────────────────────────
const MAX_TEXT_LENGTH = 10000;
const HISTORY_KEY = 'test_case_history';
const MAX_HISTORY = 20;

// ── State ──────────────────────────────────────────────
let abortController = null;
let currentRawText = '';
let currentTestCasesData = null;
let _fileStore = new DataTransfer();

// ── DOM refs ───────────────────────────────────────────
const form = document.getElementById('requirementsForm');
const textInput = document.getElementById('requirementText');
const imageInput = document.getElementById('requirementImages');
const imagePreview = document.getElementById('imagePreview');
const charCount = document.getElementById('charCount');
const textHint = document.getElementById('textHint');
const submitBtn = document.getElementById('submitBtn');
const stopBtn = document.getElementById('stopBtn');
const progressBar = document.getElementById('progressBar');
const statusText = document.getElementById('statusText');
const resultsContainer = document.getElementById('resultsContainer');
const testCasesResult = document.getElementById('testCasesResult');
const usageInfo = document.getElementById('usageInfo');
const modelSelect = document.getElementById('modelSelect');
const maxTokensInput = document.getElementById('maxTokens');
const temperatureInput = document.getElementById('temperature');
const tempValue = document.getElementById('tempValue');
const streamMode = document.getElementById('streamMode');
const exportCsvBtn = document.getElementById('exportCsvBtn');
const copyBtn = document.getElementById('copyBtn');
const historyCount = document.getElementById('historyCount');
const historyList = document.getElementById('historyList');

// ── Init ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadModels();
    loadHistory();
    bindEvents();
    updateCharCount();
});

function bindEvents() {
    form.addEventListener('submit', handleSubmit);
    stopBtn.addEventListener('click', handleStop);
    textInput.addEventListener('input', updateCharCount);
    imageInput.addEventListener('change', previewImages);
    temperatureInput.addEventListener('input', () => {
        tempValue.textContent = temperatureInput.value;
    });
    exportCsvBtn.addEventListener('click', exportCsv);
    copyBtn.addEventListener('click', copyResult);
}

// ── Model List ──────────────────────────────────────────
async function loadModels() {
    try {
        const res = await fetch('/api/models');
        const data = await readJsonResponse(res);
        if (!Array.isArray(data.models)) return;
        data.models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            modelSelect.appendChild(opt);
        });
    } catch (e) {
        // model selector keeps the default option
    }
}

// ── Char Count & Validation ─────────────────────────────
function updateCharCount() {
    const len = textInput.value.length;
    charCount.textContent = `${len} / ${MAX_TEXT_LENGTH}`;
    if (len > MAX_TEXT_LENGTH) {
        textHint.textContent = `文本过长（${len}/${MAX_TEXT_LENGTH}），请缩减后提交`;
        textHint.className = 'validation-hint error';
    } else if (len > MAX_TEXT_LENGTH * 0.8) {
        textHint.textContent = `即将达到长度上限（${len}/${MAX_TEXT_LENGTH}）`;
        textHint.className = 'validation-hint warning';
    } else {
        textHint.textContent = '';
        textHint.className = 'validation-hint';
    }
}

// ── Image Preview ───────────────────────────────────────
function previewImages() {
    // Append newly selected files to our store
    Array.from(imageInput.files).forEach(f => _fileStore.items.add(f));
    renderImagePreviews();
    imageInput.value = '';  // Reset so re-selecting same file works
}

function renderImagePreviews() {
    imagePreview.replaceChildren();
    const files = Array.from(_fileStore.files);
    files.forEach((file, i) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const div = document.createElement('div');
            div.className = 'thumb';

            const img = document.createElement('img');
            img.src = e.target.result;
            img.alt = `预览${i + 1}`;

            const name = document.createElement('span');
            name.className = 'thumb-name';
            name.textContent = file.name;

            const size = document.createElement('span');
            size.className = 'thumb-size';
            size.textContent = `${(file.size / 1024).toFixed(1)}KB`;

            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'thumb-del';
            del.textContent = '✕';
            del.title = '移除图片';
            del.addEventListener('click', (ev) => {
                ev.stopPropagation();
                removeImage(i);
            });

            div.append(img, name, size, del);
            imagePreview.appendChild(div);
        };
        reader.readAsDataURL(file);
    });
}

function removeImage(index) {
    const files = Array.from(_fileStore.files);
    files.splice(index, 1);
    _fileStore = new DataTransfer();
    files.forEach(f => _fileStore.items.add(f));
    renderImagePreviews();
}

// ── Submit ──────────────────────────────────────────────
async function handleSubmit(e) {
    e.preventDefault();

    const text = textInput.value.trim();
    const files = _fileStore.files;
    const maxTokens = Number(maxTokensInput.value);
    const temperature = Number(temperatureInput.value);

    if (!text && files.length === 0) {
        showStatus('请提供需求文本或需求图片。', 'error');
        return;
    }
    if (text.length > MAX_TEXT_LENGTH) {
        showStatus(`文本过长（${text.length}/${MAX_TEXT_LENGTH}字符），请缩减。`, 'error');
        return;
    }
    if (!Number.isInteger(maxTokens) || maxTokens < 256 || maxTokens > 16384) {
        showStatus('Max Tokens 必须是 256 到 16384 之间的整数。', 'error');
        return;
    }
    if (!Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
        showStatus('Temperature 必须在 0 到 2 之间。', 'error');
        return;
    }

    const formData = new FormData();
    if (text) formData.append('requirement_text', text);
    for (const f of files) formData.append('requirement_images', f);
    if (modelSelect.value) formData.append('model', modelSelect.value);
    formData.append('max_tokens', maxTokensInput.value);
    formData.append('temperature', temperatureInput.value);

    setLoading(true);
    testCasesResult.replaceChildren();
    resultsContainer.style.display = 'block';
    usageInfo.textContent = '';
    currentRawText = '';
    currentTestCasesData = null;

    if (streamMode.checked) {
        await handleStreamSubmit(formData);
    } else {
        await handleNormalSubmit(formData);
    }

    setLoading(false);
}

function setLoading(loading) {
    submitBtn.style.display = loading ? 'none' : '';
    stopBtn.style.display = loading ? '' : 'none';
    progressBar.style.display = loading ? 'block' : 'none';
    if (!loading) {
        progressBar.querySelector('.progress-bar-fill').style.width = '0%';
    }
}

async function readJsonResponse(res) {
    const text = await res.text();
    if (!text) return {};
    try {
        return JSON.parse(text);
    } catch (e) {
        return { error: text || res.statusText };
    }
}

// ── Normal submit ───────────────────────────────────────
async function handleNormalSubmit(formData) {
    abortController = new AbortController();
    try {
        showStatus('正在生成测试用例，请耐心等待...');
        const res = await fetch('/generate-test-cases', { method: 'POST', body: formData, signal: abortController.signal });
        const data = await readJsonResponse(res);

        console.log('[DEBUG] response:', { ok: res.ok, hasData: !!data.test_cases_data, rawLen: (data.test_cases||'').length });

        if (res.ok && (data.test_cases_data || data.test_cases)) {
            setCurrentResult(data.test_cases || '', data.test_cases_data || null);
            console.log('[DEBUG] setCurrentResult done | currentTestCasesData:', !!currentTestCasesData, '| currentRawText len:', currentRawText.length);
            if (data.usage) {
                usageInfo.textContent = `${data.usage.prompt_tokens}+${data.usage.completion_tokens} tokens | ${data.usage.duration_s}s`;
            }
            saveToHistory(currentRawText, data.usage, currentTestCasesData);
            showStatus('生成完成', 'success');
        } else {
            showStatus(`错误：${data.error || res.statusText}`, 'error');
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            showStatus(`网络错误：${err.message}`, 'error');
        }
    } finally {
        abortController = null;
    }
}

// ── Streaming submit ────────────────────────────────────
async function handleStreamSubmit(formData) {
    abortController = new AbortController();

    try {
        showStatus('正在生成（流式）...');
        const res = await fetch('/generate-test-cases-stream', {
            method: 'POST',
            body: formData,
            signal: abortController.signal
        });

        if (!res.ok) {
            const data = await readJsonResponse(res);
            showStatus(`错误：${data.error || res.statusText}`, 'error');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const payload = line.slice(6).trim();
                if (payload === '[DONE]') {
                    const parsed = parseStructuredPayload(fullText);
                    setCurrentResult(fullText, parsed);
                    saveToHistory(currentRawText, null, currentTestCasesData);
                    showStatus('生成完成', 'success');
                    return;
                }
                try {
                    const parsed = JSON.parse(payload);
                    if (parsed.error) {
                        showStatus(`错误：${parsed.error}`, 'error');
                        return;
                    }
                    if (parsed.content) {
                        fullText += parsed.content;
                        currentRawText = fullText;
                        const structured = parseStructuredPayload(fullText);
                        renderTestCases(fullText, structured);
                        testCasesResult.scrollTop = testCasesResult.scrollHeight;
                    }
                } catch (e) {
                    // skip malformed chunk
                }
            }
        }

        const parsed = parseStructuredPayload(fullText);
        setCurrentResult(fullText, parsed);
        saveToHistory(currentRawText, null, currentTestCasesData);
        showStatus('生成完成', 'success');
    } catch (err) {
        if (err.name !== 'AbortError') {
            showStatus(`流式错误：${err.message}`, 'error');
        }
    } finally {
        abortController = null;
    }
}

function handleStop() {
    if (abortController) {
        abortController.abort();
        abortController = null;
        setLoading(false);
        showStatus('已停止生成', 'warning');
    }
}

// ── Status ──────────────────────────────────────────────
function showStatus(msg, type) {
    statusText.textContent = msg || '';
    statusText.className = `status-text ${type || ''}`;
    if (type === 'success') {
        setTimeout(() => {
            if (statusText.textContent === msg) statusText.textContent = '';
        }, 5000);
    }
}

// ── Render Test Cases ───────────────────────────────────
function setCurrentResult(rawText, structuredPayload) {
    currentTestCasesData = normalizePayload(structuredPayload || parseStructuredPayload(rawText));
    currentRawText = currentTestCasesData ? formatPayloadAsText(currentTestCasesData) : rawText;
    renderTestCases(rawText, currentTestCasesData);
}

function renderTestCases(rawText, structuredPayload) {
    const normalized = normalizePayload(structuredPayload);
    if (normalized) {
        testCasesResult.innerHTML = renderStructuredPayload(normalized);
        return;
    }
    testCasesResult.innerHTML = parseLegacyTextToHtml(rawText || '');
}

function stripJsonFence(text) {
    let value = (text || '').trim();
    if (value.startsWith('```')) {
        const lines = value.split(/\r?\n/);
        if (lines[0].trim().startsWith('```')) lines.shift();
        if (lines[lines.length - 1]?.trim() === '```') lines.pop();
        value = lines.join('\n').trim();
    }
    return value;
}

function parseStructuredPayload(text) {
    const cleaned = stripJsonFence(text);
    if (!cleaned) { console.log('[DEBUG] parseStructuredPayload: empty after strip'); return null; }
    try {
        const parsed = JSON.parse(cleaned);
        const result = normalizePayload(parsed);
        if (!result) console.log('[DEBUG] parseStructuredPayload: JSON.parse OK but normalizePayload returned null', parsed);
        return result;
    } catch (e) {
        console.log('[DEBUG] parseStructuredPayload: JSON.parse failed on full text:', e.message, '| last 80 chars:', cleaned.slice(-80));
        const start = cleaned.indexOf('{');
        const end = cleaned.lastIndexOf('}');
        if (start === -1 || end <= start) { console.log('[DEBUG] parseStructuredPayload: no valid JSON block found'); return null; }
        let sliced;
        try {
            sliced = cleaned.slice(start, end + 1);
            const parsed = JSON.parse(sliced);
            const result = normalizePayload(parsed);
            if (!result) console.log('[DEBUG] parseStructuredPayload: sliced JSON OK but normalizePayload returned null');
            return result;
        } catch (ignored) {
            console.log('[DEBUG] parseStructuredPayload: sliced JSON.parse also failed:', ignored.message, '| sliced last 80 chars:', (sliced||'').slice(-80));
            return null;
        }
    }
}

function normalizePayload(payload) {
    if (!payload || !Array.isArray(payload.test_cases)) {
        console.log('[DEBUG] normalizePayload failed: no payload or test_cases not array', typeof payload, payload ? typeof payload.test_cases : 'N/A');
        return null;
    }
    const cases = payload.test_cases
        .filter(item => item && typeof item === 'object')
        .map((item, i) => ({
            id: stringValue(item.id || `TC_${String(i + 1).padStart(3, '0')}`),
            description: stringValue(item.description),
            preconditions: normalizeList(item.preconditions),
            steps: normalizeList(item.steps),
            expected_results: normalizeList(item.expected_results),
            priority: ['高', '中', '低'].includes(stringValue(item.priority)) ? stringValue(item.priority) : '中',
            type: stringValue(item.type),
            method: stringValue(item.method),
            requirement_trace: stringValue(item.requirement_trace),
            source_evidence: stringValue(item.source_evidence)
        }));
    if (cases.length === 0) {
        console.log('[DEBUG] normalizePayload: all items filtered out, original count:', payload.test_cases.length);
        return null;
    }
    console.log('[DEBUG] normalizePayload: OK,', cases.length, 'cases');
    const coverage = payload.coverage_summary || {};
    return {
        test_cases: cases,
        coverage_summary: {
            covered_points: normalizeList(coverage.covered_points),
            risk_points: normalizeList(coverage.risk_points)
        }
    };
}

function normalizeList(value) {
    if (Array.isArray(value)) return value.map(stringValue).filter(Boolean);
    const single = stringValue(value);
    return single ? [single] : [];
}

function stringValue(value) {
    return value === undefined || value === null ? '' : String(value).trim();
}

function renderStructuredPayload(payload) {
    const casesHtml = payload.test_cases.map(tc => {
        const pClass = tc.priority === '高' ? 'priority-high' : tc.priority === '中' ? 'priority-mid' : 'priority-low';
        return `<div class="tc-card">
            <div class="tc-header">
                <span class="tc-id">${escapeHtml(tc.id)}</span>
                <span class="tc-priority ${pClass}">${escapeHtml(tc.priority)}</span>
            </div>
            <div class="tc-body">
                <div class="tc-field"><strong>描述：</strong>${escapeHtml(tc.description)}</div>
                ${tc.type ? `<div class="tc-field"><strong>类型：</strong>${escapeHtml(tc.type)}</div>` : ''}
                ${tc.method ? `<div class="tc-field"><strong>测试方法：</strong>${escapeHtml(tc.method)}</div>` : ''}
                ${tc.requirement_trace ? `<div class="tc-field"><strong>需求追踪：</strong>${escapeHtml(tc.requirement_trace)}</div>` : ''}
                ${tc.source_evidence ? `<div class="tc-field"><strong>来源证据：</strong>${escapeHtml(tc.source_evidence)}</div>` : ''}
                <div class="tc-field"><strong>前置条件：</strong>${formatList(tc.preconditions)}</div>
                <div class="tc-field"><strong>测试步骤：</strong>${formatList(tc.steps)}</div>
                <div class="tc-field"><strong>预期结果：</strong>${formatList(tc.expected_results)}</div>
            </div>
        </div>`;
    }).join('');

    const coverage = payload.coverage_summary || {};
    const mc = coverage.method_coverage || {};
    const usedMethods = Object.entries(mc).filter(([, v]) => v).map(([k]) => k);
    const unusedMethods = Object.entries(mc).filter(([, v]) => !v).map(([k]) => k);
    const methodHtml = usedMethods.length || unusedMethods.length
        ? `<div class="tc-field">
            <strong>测试方法覆盖：</strong>
            ${usedMethods.length ? `<span class="method-used">${usedMethods.map(m => `<span class="method-tag used">${escapeHtml(m)}</span>`).join(' ')}</span>` : ''}
            ${unusedMethods.length ? `<span class="method-unused"><span class="method-tag unused">未使用: ${unusedMethods.map(m => escapeHtml(m)).join(', ')}</span></span>` : ''}
        </div>`
        : '';
    const summaryHtml = (coverage.covered_points.length || coverage.risk_points.length || methodHtml)
        ? `<div class="coverage-summary">
            ${methodHtml}
            ${coverage.covered_points.length ? `<div class="tc-field"><strong>覆盖点：</strong>${formatList(coverage.covered_points)}</div>` : ''}
            ${coverage.risk_points.length ? `<div class="tc-field"><strong>待确认风险：</strong>${formatList(coverage.risk_points)}</div>` : ''}
        </div>`
        : '';

    return casesHtml + summaryHtml;
}

function parseLegacyTextToHtml(text) {
    const blocks = text.split(/(?=测试用例编号[：:])/);
    if (blocks.length <= 1) {
        return `<pre class="raw-output">${escapeHtml(text)}</pre>`;
    }
    return blocks.map(block => {
        if (!block.trim()) return '';
        const id = extractField(block, /测试用例编号[：:]\s*(.+)/);
        const desc = extractField(block, /测试用例描述[：:]\s*(.+)/);
        const precond = extractMultiField(block, /前置条件[：:]/);
        const steps = extractMultiField(block, /测试步骤[：:]/);
        const expected = extractMultiField(block, /预期结果[：:]/);
        const priority = extractField(block, /优先级[：:]\s*(.+)/);
        const pClass = (priority || '').includes('高') ? 'priority-high' :
                       (priority || '').includes('中') ? 'priority-mid' : 'priority-low';

        return `<div class="tc-card">
            <div class="tc-header">
                <span class="tc-id">${escapeHtml(id || '')}</span>
                <span class="tc-priority ${pClass}">${escapeHtml(priority || '')}</span>
            </div>
            <div class="tc-body">
                <div class="tc-field"><strong>描述：</strong>${escapeHtml(desc || '')}</div>
                ${extractField(block, /类型[：:]\s*(.+)/) ? `<div class="tc-field"><strong>类型：</strong>${escapeHtml(extractField(block, /类型[：:]\s*(.+)/))}</div>` : ''}
                ${extractField(block, /测试方法[：:]\s*(.+)/) ? `<div class="tc-field"><strong>测试方法：</strong>${escapeHtml(extractField(block, /测试方法[：:]\s*(.+)/))}</div>` : ''}
                <div class="tc-field"><strong>前置条件：</strong>${formatMulti(precond)}</div>
                <div class="tc-field"><strong>测试步骤：</strong>${formatMulti(steps)}</div>
                <div class="tc-field"><strong>预期结果：</strong>${formatMulti(expected)}</div>
            </div>
        </div>`;
    }).join('');
}

function extractField(text, re) {
    const m = text.match(re);
    return m ? m[1].trim() : '';
}

function extractMultiField(text, re) {
    const idx = text.search(re);
    if (idx === -1) return '';
    const after = text.slice(idx).split('\n').slice(1);
    const items = [];
    for (const line of after) {
        const trimmed = line.trim();
        if (!trimmed) break;
        if (/^(测试用例|测试方法|前置条件|测试步骤|预期结果|优先级|类型|需求追踪|来源证据)[：:]/.test(trimmed)) break;
        items.push(trimmed);
    }
    return items.join('\n');
}

function formatList(items) {
    if (!items || items.length === 0) return '<span class="empty-field">（无）</span>';
    return '<ol>' + items.map(item => `<li>${escapeHtml(stripListPrefix(item))}</li>`).join('') + '</ol>';
}

function formatMulti(text) {
    return formatList((text || '').split('\n').filter(l => l.trim()));
}

function stripListPrefix(text) {
    return stringValue(text).replace(/^\d+[\.\、\)\s]*/, '');
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function formatPayloadAsText(payload) {
    return payload.test_cases.map(tc => {
        const lines = [
            `测试用例编号：${tc.id}`,
            `测试用例描述：${tc.description}`,
            '前置条件：',
            ...tc.preconditions.map((item, i) => `${i + 1}. ${item}`),
            '',
            '测试步骤：',
            ...tc.steps.map((item, i) => `${i + 1}. ${item}`),
            '',
            '预期结果：',
            ...tc.expected_results.map((item, i) => `${i + 1}. ${item}`),
            '',
        ];
        if (tc.type) lines.push(`类型：${tc.type}`);
        if (tc.method) lines.push(`测试方法：${tc.method}`);
        if (tc.requirement_trace) lines.push(`需求追踪：${tc.requirement_trace}`);
        if (tc.source_evidence) lines.push(`来源证据：${tc.source_evidence}`);
        lines.push(`优先级：${tc.priority}`);
        return lines.join('\n');
    }).join('\n\n');
}

// ── CSV Export ──────────────────────────────────────────
function exportCsv() {
    console.log('[DEBUG] exportCsv | currentTestCasesData:', !!currentTestCasesData, '| currentRawText len:', currentRawText.length, '| rawText preview:', currentRawText.slice(0, 100));
    let payload = currentTestCasesData;
    if (!payload) {
        payload = parseStructuredPayload(currentRawText);
        console.log('[DEBUG] exportCsv | parseStructuredPayload result:', !!payload);
    }
    let rows = payload ? rowsFromStructured(payload) : null;
    if (!rows) {
        rows = rowsFromLegacy(currentRawText);
        console.log('[DEBUG] exportCsv | rowsFromLegacy count:', rows ? rows.length : 0);
    }
    if (!rows || rows.length <= 1) {
        showStatus('\u6CA1\u6709\u53EF\u5BFC\u51FA\u7684\u6D4B\u8BD5\u7528\u4F8B\u6570\u636E', 'error');
        return;
    }

    const csv = '\uFEFF' + rows
        .map(r => r.map(escapeCsvCell).join(','))
        .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test_cases_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showStatus('CSV \u5BFC\u51FA\u6210\u529F', 'success');
}

function rowsFromStructured(payload) {
    const rows = [['编号', '描述', '类型', '测试方法', '需求追踪', '来源证据', '前置条件', '测试步骤', '预期结果', '优先级']];
    payload.test_cases.forEach(tc => {
        rows.push([
            tc.id,
            tc.description,
            tc.type,
            tc.method,
            tc.requirement_trace,
            tc.source_evidence,
            tc.preconditions.join('; '),
            tc.steps.join('; '),
            tc.expected_results.join('; '),
            tc.priority
        ]);
    });
    return rows;
}

function rowsFromLegacy(text) {
    const blocks = (text || '').split(/(?=测试用例编号[：:])/);
    const rows = [['编号', '描述', '类型', '测试方法', '需求追踪', '来源证据', '前置条件', '测试步骤', '预期结果', '优先级']];
    blocks.forEach(block => {
        if (!block.trim()) return;
        rows.push([
            extractField(block, /测试用例编号[：:]\s*(.+)/),
            extractField(block, /测试用例描述[：:]\s*(.+)/),
            extractField(block, /类型[：:]\s*(.+)/),
            extractField(block, /测试方法[：:]\s*(.+)/),
            extractField(block, /需求追踪[：:]\s*(.+)/),
            extractField(block, /来源证据[：:]\s*(.+)/),
            toCsvCell(extractMultiField(block, /前置条件[：:]/)),
            toCsvCell(extractMultiField(block, /测试步骤[：:]/)),
            toCsvCell(extractMultiField(block, /预期结果[：:]/)),
            extractField(block, /优先级[：:]\s*(.+)/)
        ]);
    });
    return rows;
}

function escapeCsvCell(value) {
    let text = stringValue(value);
    if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
}

function toCsvCell(text) {
    return (text || '').split('\n').filter(l => l.trim()).map(stripListPrefix).join('; ');
}

function copyResult() {
    const text = currentRawText || testCasesResult.innerText || testCasesResult.textContent;
    if (!text) {
        showStatus('没有可复制的内容', 'error');
        return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showStatus('已复制到剪贴板', 'success');
        }).catch(() => {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        showStatus('已复制到剪贴板', 'success');
    } catch (e) {
        showStatus('复制失败，请手动选择文本后 Ctrl+C', 'error');
    }
    document.body.removeChild(textarea);
}

// ── History (localStorage) ──────────────────────────────
function saveToHistory(text, usage, payload) {
    if (!text || text.length < 20) return;
    try {
        const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        history.unshift({
            time: new Date().toISOString(),
            preview: text.slice(0, 200).replace(/\n/g, ' '),
            text,
            payload: payload || null,
            usage: usage || null
        });
        if (history.length > MAX_HISTORY) history.length = MAX_HISTORY;
        localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        renderHistory(history);
    } catch (e) {
        // quota exceeded or malformed storage
    }
}

function loadHistory() {
    try {
        const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        renderHistory(history);
    } catch (e) {
        renderHistory([]);
    }
}

function renderHistory(history) {
    historyCount.textContent = history.length;
    historyList.replaceChildren();

    history.forEach((h, i) => {
        const item = document.createElement('div');
        item.className = 'history-item';

        const time = document.createElement('span');
        time.className = 'history-time';
        time.textContent = new Date(h.time).toLocaleString('zh-CN');

        const preview = document.createElement('span');
        preview.className = 'history-preview';
        preview.textContent = h.preview || '';

        const loadBtn = document.createElement('button');
        loadBtn.className = 'btn-tiny load-history';
        loadBtn.type = 'button';
        loadBtn.textContent = '加载';
        loadBtn.addEventListener('click', () => {
            const latest = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')[i];
            if (!latest) return;
            setCurrentResult(latest.text, latest.payload);
            resultsContainer.style.display = 'block';
            usageInfo.textContent = latest.usage ? `${latest.usage.prompt_tokens}+${latest.usage.completion_tokens} tokens` : '';
        });

        const delBtn = document.createElement('button');
        delBtn.className = 'btn-tiny del-history';
        delBtn.type = 'button';
        delBtn.textContent = '删除';
        delBtn.addEventListener('click', () => {
            const latest = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
            latest.splice(i, 1);
            localStorage.setItem(HISTORY_KEY, JSON.stringify(latest));
            renderHistory(latest);
        });

        item.append(time, preview, loadBtn, delBtn);
        historyList.appendChild(item);
    });
}
