// State Management
let currentTaskId = null;
let pollInterval = null;
let currentReportData = null;
let activeTab = 'dashboard';
let activeClaimNumber = null;
let lastLogMessage = '';

// Dom Elements
const dom = {
    // Navigation
    navDashboard: document.getElementById('nav-btn-dashboard'),
    navConfig: document.getElementById('nav-btn-config'),
    tabDashboard: document.getElementById('tab-dashboard'),
    tabConfig: document.getElementById('tab-config'),
    tabReport: document.getElementById('tab-report'),
    pageTitle: document.getElementById('page-title'),
    activeModelBadge: document.getElementById('active-model-badge'),
    statusIndicator: document.getElementById('status-indicator'),
    statusText: document.getElementById('status-text'),

    // History
    historyList: document.getElementById('history-list'),

    // Dashboard Upload
    analyzeForm: document.getElementById('analyze-form'),
    dropArea: document.getElementById('drop-area'),
    fileInput: document.getElementById('file-input'),
    fileInfoText: document.getElementById('file-info-text'),
    paramTolerance: document.getElementById('param-tolerance'),
    valTolerance: document.getElementById('val-tolerance'),
    paramMaxRefs: document.getElementById('param-max-refs'),
    paramClaims: document.getElementById('param-claims'),
    paramNoLlm: document.getElementById('param-no-llm'),
    btnAnalyze: document.getElementById('btn-analyze'),

    // Live Progress Console
    consoleCard: document.getElementById('console-card'),
    taskStatusBadge: document.getElementById('task-status-badge'),
    taskPdfName: document.getElementById('task-pdf-name'),
    taskProgressFill: document.getElementById('task-progress-fill'),
    taskProgressLabel: document.getElementById('task-progress-label'),
    taskStatusMsg: document.getElementById('task-status-msg'),
    consoleLogs: document.getElementById('console-logs'),

    // Config Panel
    configForm: document.getElementById('config-form'),
    configLlmAgent: document.getElementById('config-llm-agent'),
    configLlmModel: document.getElementById('config-llm-model'),
    configLlmApiKey: document.getElementById('config-llm-api-key'),
    configSearchMax: document.getElementById('config-search-max'),
    configSearchKipris: document.getElementById('config-search-kipris'),
    configSearchEpoKey: document.getElementById('config-search-epo-key'),
    configSearchEpoSecret: document.getElementById('config-search-epo-secret'),
    configSearchOpenAlexEmail: document.getElementById('config-search-openalex-email'),
    configRagVdb: document.getElementById('config-rag-vdb'),
    configRagEmbedding: document.getElementById('config-rag-embedding'),
    configSaveStatus: document.getElementById('config-save-status'),

    // Report Viewer
    reportTimestamp: document.getElementById('report-timestamp'),
    reportPatentTitle: document.getElementById('report-patent-title'),
    reportReferenceDate: document.getElementById('report-reference-date'),
    reportDateType: document.getElementById('report-date-type'),
    reportClaimsCount: document.getElementById('report-claims-count'),
    btnDownloadJson: document.getElementById('btn-download-json'),
    btnDownloadCsv: document.getElementById('btn-download-csv'),
    btnClaimListTab: document.getElementById('btn-claim-list-tab'),
    btnClaimTreeTab: document.getElementById('btn-claim-tree-tab'),
    claimsListContainer: document.getElementById('claims-list-container'),
    claimsTreeContainer: document.getElementById('claims-tree-container'),
    reportClaimsList: document.getElementById('report-claims-list'),
    reportClaimsTree: document.getElementById('report-claims-tree'),
    emptyDetailsMsg: document.getElementById('empty-details-msg'),
    detailsContent: document.getElementById('details-content'),
    detailClaimTitle: document.getElementById('detail-claim-title'),
    detailClaimBadge: document.getElementById('detail-claim-badge'),
    detailMatchStatusBadge: document.getElementById('detail-match-status-badge'),
    detailClaimText: document.getElementById('detail-claim-text'),
    refAccordionList: document.getElementById('ref-accordion-list')
};

// LLM Agent to Model Mapping
const agentModels = {
    codex: [
        { value: 'gpt-5-codex', text: 'GPT-5 Codex (CLI Default)' },
        { value: 'gpt-5', text: 'GPT-5' },
        { value: 'gpt-5-mini', text: 'GPT-5 Mini' }
    ],
    claude: [
        { value: 'claude-3-5-sonnet-20241022', text: 'Claude 3.5 Sonnet' },
        { value: 'claude-opus-4-7', text: 'Claude Opus 4.7 (CLI Default)' },
        { value: 'claude-3-opus-20240229', text: 'Claude 3 Opus' },
        { value: 'claude-3-5-haiku-20241022', text: 'Claude 3.5 Haiku' }
    ],
    gemini: [
        { value: 'gemini-2.0-flash', text: 'Gemini 2.0 Flash' },
        { value: 'gemini-2.0-flash-lite', text: 'Gemini 2.0 Flash Lite' },
        { value: 'gemini-1.5-pro', text: 'Gemini 1.5 Pro' },
        { value: 'gemini-1.5-flash', text: 'Gemini 1.5 Flash' },
        { value: 'gemini-2.0-pro-exp-02-05', text: 'Gemini 2.0 Pro Experimental' }
    ],
    openai: [
        { value: 'gpt-4o', text: 'GPT-4o' },
        { value: 'gpt-4o-mini', text: 'GPT-4o Mini' },
        { value: 'o1-preview', text: 'o1 Preview' },
        { value: 'o1-mini', text: 'o1 Mini' }
    ]
};

function updateModelOptions(agent, selectedModelValue = '') {
    const models = agentModels[agent] || [];
    dom.configLlmModel.innerHTML = '';
    
    let found = false;
    models.forEach(model => {
        const opt = document.createElement('option');
        opt.value = model.value;
        opt.textContent = model.text;
        dom.configLlmModel.appendChild(opt);
        if (model.value === selectedModelValue) {
            found = true;
        }
    });
    
    // If current configured value is not in predefined list, dynamically append it
    if (selectedModelValue && !found) {
        const opt = document.createElement('option');
        opt.value = selectedModelValue;
        opt.textContent = `${selectedModelValue} (현재 설정값)`;
        dom.configLlmModel.appendChild(opt);
    }
    
    if (selectedModelValue) {
        dom.configLlmModel.value = selectedModelValue;
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    loadConfiguration();
    loadHistory();
    setupEventListeners();
    checkConnection();
    
    // Poll connection status every 10 seconds
    setInterval(checkConnection, 10000);
});

// Setup Event Listeners
function setupEventListeners() {
    // Tab switching
    dom.navDashboard.addEventListener('click', () => switchTab('dashboard'));
    dom.navConfig.addEventListener('click', () => switchTab('config'));

    // Config form
    dom.configForm.addEventListener('submit', handleConfigSubmit);
    
    // Config Agent select change
    dom.configLlmAgent.addEventListener('change', (e) => {
        updateModelOptions(e.target.value);
    });

    // Range slider feedback
    dom.paramTolerance.addEventListener('input', (e) => {
        dom.valTolerance.textContent = `${Math.round(e.target.value * 100)}%`;
    });

    // File Drag and Drop events
    ['dragenter', 'dragover'].forEach(eventName => {
        dom.dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dom.dropArea.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dom.dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dom.dropArea.classList.remove('dragover');
        }, false);
    });

    dom.dropArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            dom.fileInput.files = files;
            updateFileInfo();
        }
    });

    dom.dropArea.addEventListener('click', () => {
        dom.fileInput.click();
    });

    dom.fileInput.addEventListener('change', updateFileInfo);

    // Analyze Submit Form
    dom.analyzeForm.addEventListener('submit', handleAnalyzeSubmit);

    // Report sub-tabs
    dom.btnClaimListTab.addEventListener('click', () => {
        dom.btnClaimListTab.classList.add('active');
        dom.btnClaimTreeTab.classList.remove('active');
        dom.claimsListContainer.classList.add('active');
        dom.claimsTreeContainer.classList.remove('active');
    });

    dom.btnClaimTreeTab.addEventListener('click', () => {
        dom.btnClaimTreeTab.classList.add('active');
        dom.btnClaimListTab.classList.remove('active');
        dom.claimsTreeContainer.classList.add('active');
        dom.claimsListContainer.classList.remove('active');
    });
}

// Check API Connection Health
async function checkConnection() {
    try {
        const res = await fetch('/api/config');
        if (res.ok) {
            dom.statusIndicator.className = 'status-dot online';
            dom.statusText.textContent = '서버 연결됨';
        } else {
            throw new Error('Not OK');
        }
    } catch (e) {
        dom.statusIndicator.className = 'status-dot offline';
        dom.statusText.textContent = '서버 연결 끊김';
    }
}

// Switch Active Navigation Tab
function switchTab(tabName) {
    activeTab = tabName;
    
    // Reset active classes
    dom.navDashboard.classList.remove('active');
    dom.navConfig.classList.remove('active');
    dom.tabDashboard.classList.remove('active');
    dom.tabConfig.classList.remove('active');
    dom.tabReport.classList.remove('active');

    if (tabName === 'dashboard') {
        dom.navDashboard.classList.add('active');
        dom.tabDashboard.classList.add('active');
        dom.pageTitle.textContent = '특허 선행기술조사 대시보드';
    } else if (tabName === 'config') {
        dom.navConfig.classList.add('active');
        dom.tabConfig.classList.add('active');
        dom.pageTitle.textContent = '시스템 구성 및 API 설정';
    } else if (tabName === 'report') {
        dom.tabReport.classList.add('active');
        dom.pageTitle.textContent = '특허 분석 보고서';
    }
}

// Load configurations from backend
async function loadConfiguration() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error('Failed to fetch config');
        const config = await res.json();

        // Populate fields
        const agent = config.llm?.agent || 'claude';
        dom.configLlmAgent.value = agent;
        updateModelOptions(agent, config.llm?.model || '');
        
        dom.configLlmApiKey.value = config.llm?.api_key || '';
        dom.configSearchMax.value = config.search?.max_results || 10;
        dom.configSearchKipris.value = config.search?.kipris_api_key || '';
        dom.configSearchEpoKey.value = config.search?.epo_ops_key || '';
        dom.configSearchEpoSecret.value = config.search?.epo_ops_secret || '';
        dom.configSearchOpenAlexEmail.value = config.search?.openalex_email || '';
        dom.configRagVdb.value = config.rag?.vector_db || 'qdrant';
        dom.configRagEmbedding.value = config.rag?.embedding_model || 'BAAI/bge-m3';

        // Update top active model badge
        dom.activeModelBadge.textContent = `${agent.toUpperCase()}: ${config.llm?.model}`;
    } catch (e) {
        console.error('Error loading config:', e);
        dom.activeModelBadge.textContent = '설정 오류';
    }
}

// Handle Config Submissions
async function handleConfigSubmit(e) {
    e.preventDefault();
    dom.configSaveStatus.textContent = '저장 중...';
    dom.configSaveStatus.className = 'save-status-text';
    
    const payload = {
        llm: {
            agent: dom.configLlmAgent.value,
            model: dom.configLlmModel.value,
            api_key: dom.configLlmApiKey.value
        },
        search: {
            max_results: parseInt(dom.configSearchMax.value, 10),
            kipris_api_key: dom.configSearchKipris.value,
            epo_ops_key: dom.configSearchEpoKey.value,
            epo_ops_secret: dom.configSearchEpoSecret.value,
            openalex_email: dom.configSearchOpenAlexEmail.value
        },
        rag: {
            vector_db: dom.configRagVdb.value,
            embedding_model: dom.configRagEmbedding.value
        }
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) throw new Error('Save failed');
        
        dom.configSaveStatus.textContent = '설정이 성공적으로 저장되었습니다.';
        dom.configSaveStatus.className = 'save-status-text success';
        loadConfiguration();
        
        setTimeout(() => {
            dom.configSaveStatus.textContent = '';
        }, 3000);
    } catch (err) {
        dom.configSaveStatus.textContent = '설정 저장 중 오류가 발생했습니다.';
        dom.configSaveStatus.className = 'save-status-text error';
    }
}

// Update file info display on drop/select
function updateFileInfo() {
    const file = dom.fileInput.files[0];
    if (file) {
        dom.fileInfoText.textContent = `${file.name} (${formatBytes(file.size)})`;
        dom.btnAnalyze.disabled = false;
    } else {
        dom.fileInfoText.textContent = '선택된 파일 없음';
        dom.btnAnalyze.disabled = true;
    }
}

// Format byte size
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Handle pipeline start request
async function handleAnalyzeSubmit(e) {
    e.preventDefault();
    const file = dom.fileInput.files[0];
    if (!file) return;

    dom.btnAnalyze.disabled = true;
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('tolerance', dom.paramTolerance.value);
    formData.append('max_refs', dom.paramMaxRefs.value);
    formData.append('no_llm', dom.paramNoLlm.checked);
    if (dom.paramClaims.value.trim()) {
        formData.append('claims', dom.paramClaims.value.trim());
    }

    // Reset console
    dom.consoleCard.style.display = 'block';
    dom.taskStatusBadge.className = 'badge badge-running';
    dom.taskStatusBadge.textContent = '대기 중';
    dom.taskPdfName.textContent = file.name;
    dom.taskProgressFill.style.width = '0%';
    dom.taskProgressLabel.textContent = '0%';
    dom.taskStatusMsg.textContent = '서버에 요청 중...';
    dom.consoleLogs.innerHTML = '<div class="log-line system">[system] 파일 업로드 완료. 분석 스케줄링 중...</div>';
    lastLogMessage = '';
    
    try {
        const res = await fetch('/api/analyze', {
            method: 'POST',
            body: formData
        });
        
        if (!res.ok) throw new Error('Analysis start failed');
        const data = await res.json();
        
        currentTaskId = data.task_id;
        startPollingTask(currentTaskId);
    } catch (err) {
        appendLog('error', `[system] 파일 업로드 및 분석 시작 실패: ${err.message}`);
        dom.taskStatusBadge.className = 'badge badge-danger';
        dom.taskStatusBadge.textContent = '에러 발생';
        dom.taskStatusMsg.textContent = '작업 시작 오류';
        dom.btnAnalyze.disabled = false;
    }
}

// Start polling backend for task updates
function startPollingTask(taskId) {
    if (pollInterval) clearInterval(pollInterval);
    
    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/tasks/${taskId}`);
            if (!res.ok) throw new Error('Polling error');
            const task = await res.json();

            // Update UI components
            dom.taskProgressFill.style.width = `${task.progress}%`;
            dom.taskProgressLabel.textContent = `${task.progress}%`;
            dom.taskStatusMsg.textContent = task.message;

            // Update console logs
            if (task.message && task.message !== lastLogMessage) {
                let logType = 'info';
                if (task.status === 'success') logType = 'success';
                if (task.status === 'failed') logType = 'error';
                
                appendLog(logType, `[pipeline] ${task.message}`);
                lastLogMessage = task.message;
            }

            if (task.status === 'success') {
                clearInterval(pollInterval);
                dom.taskStatusBadge.className = 'badge badge-success';
                dom.taskStatusBadge.textContent = '완료';
                appendLog('success', '[system] 분석이 성공적으로 마무리되었습니다. 보고서를 로딩합니다.');
                
                // Show report tab
                currentReportData = task.result;
                renderReport(currentReportData, taskId);
                switchTab('report');
                loadHistory();
                
                // Re-enable run button
                dom.btnAnalyze.disabled = false;
            } else if (task.status === 'failed') {
                clearInterval(pollInterval);
                dom.taskStatusBadge.className = 'badge badge-danger';
                dom.taskStatusBadge.textContent = '실패';
                appendLog('error', `[system] 분석 실패: ${task.error}`);
                loadHistory();
                
                // Re-enable run button
                dom.btnAnalyze.disabled = false;
            } else {
                dom.taskStatusBadge.className = 'badge badge-running';
                dom.taskStatusBadge.textContent = '분석 중';
            }
        } catch (err) {
            console.error('Polling error:', err);
        }
    }, 1000);
}

// Append logs to visual console
function appendLog(type, text) {
    const el = document.createElement('div');
    el.className = `log-line ${type}`;
    
    const timestamp = new Date().toLocaleTimeString();
    el.textContent = `[${timestamp}] ${text}`;
    
    dom.consoleLogs.appendChild(el);
    dom.consoleLogs.scrollTop = dom.consoleLogs.scrollHeight;
}

// Load historical items
async function loadHistory() {
    try {
        const res = await fetch('/api/history');
        if (!res.ok) throw new Error('Failed to load history');
        const history = await res.json();

        dom.historyList.innerHTML = '';
        if (history.length === 0) {
            dom.historyList.innerHTML = '<div class="loading-small">이전 분석 기록이 없습니다.</div>';
            return;
        }

        history.forEach(item => {
            const el = document.createElement('div');
            el.className = 'history-item';
            if (currentTaskId === item.task_id) el.classList.add('active');
            
            // Format timestamp slightly cleaner
            let timeStr = item.timestamp;
            try {
                const d = new Date(item.timestamp);
                timeStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } catch(e){}

            el.innerHTML = `
                <div class="hist-title" title="${item.patent_title}">${item.patent_title}</div>
                <div class="hist-meta">
                    <span>${timeStr}</span>
                    <span class="hist-status ${item.status}"></span>
                </div>
            `;

            el.addEventListener('click', () => {
                // Remove active classes
                document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
                el.classList.add('active');
                loadReportFromHistory(item.task_id);
            });

            dom.historyList.appendChild(el);
        });
    } catch (e) {
        console.error('History load failed:', e);
        dom.historyList.innerHTML = '<div class="loading-small" style="color:var(--danger)">이력 불러오기 실패</div>';
    }
}

// Load specific report from history item click
async function loadReportFromHistory(taskId) {
    currentTaskId = taskId;
    try {
        const res = await fetch(`/api/reports/${taskId}`);
        if (!res.ok) {
            // Task might have failed or still running
            const taskRes = await fetch(`/api/tasks/${taskId}`);
            const task = await taskRes.json();
            if (task.status === 'running') {
                currentTaskId = taskId;
                // Switch to dashboard and attach polling
                switchTab('dashboard');
                dom.consoleCard.style.display = 'block';
                dom.taskPdfName.textContent = task.pdf_filename;
                dom.taskProgressFill.style.width = `${task.progress}%`;
                dom.taskProgressLabel.textContent = `${task.progress}%`;
                dom.taskStatusMsg.textContent = task.message;
                dom.consoleLogs.innerHTML = `<div class="log-line system">[system] 기존 진행 중인 작업을 이어받았습니다.</div>`;
                startPollingTask(taskId);
                return;
            } else if (task.status === 'failed') {
                alert(`해당 작업은 실패했습니다. 에러: ${task.error}`);
                return;
            }
            throw new Error('Not found');
        }
        const report = await res.json();
        currentReportData = report;
        renderReport(report, taskId);
        switchTab('report');
    } catch (e) {
        alert('보고서 파일을 로드하지 못했습니다.');
    }
}

// Render patent report details onto Report tab
function renderReport(report, taskId) {
    const meta = report.metadata;
    
    // Set text contents
    dom.reportPatentTitle.textContent = meta.title || '발명 명칭 없음';
    dom.reportReferenceDate.textContent = meta.reference_date || '-';
    dom.reportDateType.textContent = meta.date_type === 'priority' ? '우선일' : (meta.date_type === 'filing' ? '출원일' : meta.date_type || '-');
    dom.reportClaimsCount.textContent = `${meta.total_claims}개 (매칭률: ${Math.round(meta.coverage_rate * 100)}%)`;
    
    let processedStr = meta.processed_at || '-';
    dom.reportTimestamp.textContent = `분석 완료일: ${processedStr}`;

    // Set download buttons URLs
    dom.btnDownloadJson.onclick = () => window.open(`/api/reports/${taskId}/download?format=json`);
    dom.btnDownloadCsv.onclick = () => window.open(`/api/reports/${taskId}/download?format=csv`);

    // Render claims list sidebar
    dom.reportClaimsList.innerHTML = '';
    
    const matches = report.claim_matches || [];
    
    matches.forEach(cm => {
        const item = document.createElement('div');
        item.className = 'claim-list-item';
        if (activeClaimNumber === cm.claim_number) item.classList.add('active');

        const kind = cm.is_independent ? '독립항' : '종속항';
        
        let badgeClass = 'safe';
        let badgeText = '안전';
        
        if (cm.is_covered) {
            badgeClass = 'critical';
            badgeText = '매칭';
        } else {
            // Check if there are matches but not covered
            const hasRefs = (cm.primary_reference || cm.secondary_references?.length > 0);
            if (hasRefs) {
                badgeClass = 'partial';
                badgeText = '주의';
            }
        }

        const previewText = (cm.claim_text || '').replace(/\s+/g, ' ');

        item.innerHTML = `
            <div class="item-header">
                <span class="item-title">청구항 ${cm.claim_number} (${kind})</span>
                <span class="claim-score-badge ${badgeClass}">${badgeText}</span>
            </div>
            <div class="item-preview">${previewText || '청구항 원문 내용 없음'}</div>
        `;

        item.addEventListener('click', () => {
            document.querySelectorAll('.claim-list-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            activeClaimNumber = cm.claim_number;
            renderClaimDetails(cm);
        });

        dom.reportClaimsList.appendChild(item);
    });

    // Render tree
    dom.reportClaimsTree.innerHTML = '';
    const pre = document.createElement('pre');
    pre.textContent = meta.dependency_tree || '의존성 트리 결과가 없습니다.';
    dom.reportClaimsTree.appendChild(pre);

    // Reset details view
    dom.emptyDetailsMsg.style.display = 'flex';
    dom.detailsContent.style.display = 'none';
    activeClaimNumber = null;
}

// Render selected claim match details
function renderClaimDetails(cm) {
    dom.emptyDetailsMsg.style.display = 'none';
    dom.detailsContent.style.display = 'block';

    dom.detailClaimTitle.textContent = `청구항 ${cm.claim_number}`;
    dom.detailClaimBadge.textContent = cm.is_independent ? '독립항' : '종속항';
    dom.detailClaimText.textContent = cm.claim_text || '청구항 본문 내용이 없습니다.';

    // Matching Status Badge
    let statusClass = 'safe';
    let statusText = '선행문헌 없음 (안전)';
    if (cm.is_covered) {
        statusClass = 'critical';
        statusText = '거절 의견 매칭 발견 (위험)';
    } else {
        const hasRefs = (cm.primary_reference || cm.secondary_references?.length > 0);
        if (hasRefs) {
            statusClass = 'partial';
            statusText = '의심 인용 문헌 존재 (주의)';
        }
    }
    
    dom.detailMatchStatusBadge.className = `matching-status-badge ${statusClass}`;
    dom.detailMatchStatusBadge.textContent = statusText;

    // Accordions
    dom.refAccordionList.innerHTML = '';
    let refIndex = 1;

    // Helper to render doc
    const addDocReference = (doc, isPrimary) => {
        if (!doc) return;
        const refItem = document.createElement('div');
        refItem.className = 'ref-item';

        const scorePct = Math.round(doc.similarity_score * 100);
        const verifiedBadge = doc.paragraph_verified 
            ? '<span class="verification-badge verified">검증 완료 (LLM Verified)</span>' 
            : '<span class="verification-badge unverified">미검증 (Unverified)</span>';

        const coversText = doc.covers_claims && doc.covers_claims.length > 0 
            ? doc.covers_claims.join(', ') 
            : '없음';

        refItem.innerHTML = `
            <div class="ref-header">
                <div class="ref-info-left">
                    <div class="ref-index">${isPrimary ? '主' : refIndex++}</div>
                    <div>
                        <span class="ref-doc-id">${doc.doc_id}</span>
                        <p class="ref-title">${doc.title || '제목 없음'}</p>
                    </div>
                </div>
                <div class="ref-header-right">
                    <span class="ref-score">유사도 ${scorePct}%</span>
                    <svg class="ref-arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </div>
            </div>
            <div class="ref-body">
                <div class="ref-metadata-grid">
                    <div class="ref-meta-box">
                        <div class="m-label">출처 (Source)</div>
                        <div class="m-val">${doc.source?.toUpperCase() || '-'}</div>
                    </div>
                    <div class="ref-meta-box">
                        <div class="m-label">공개/등록일</div>
                        <div class="m-val">${doc.pub_date || '-'}</div>
                    </div>
                    <div class="ref-meta-box">
                        <div class="m-label">커버 청구항 목록</div>
                        <div class="m-val">${coversText}</div>
                    </div>
                    <div class="ref-meta-box">
                        <div class="m-label">원문 링크</div>
                        <div class="m-val">
                            ${doc.url ? `<a href="${doc.url}" target="_blank">특허 사이트 이동</a>` : '제공 안 됨'}
                        </div>
                    </div>
                </div>
                
                <div class="ref-matched-block">
                    <div class="verification-status-row">
                        <h5>매칭 단락 (Matched Paragraph)</h5>
                        ${verifiedBadge}
                    </div>
                    <div class="paragraph-content">
                        ${doc.matched_paragraph || '단락 매칭 분석 결과가 없습니다.'}
                    </div>
                </div>
            </div>
        `;

        // Toggle Accordion Click handler
        refItem.querySelector('.ref-header').addEventListener('click', () => {
            refItem.classList.toggle('open');
        });

        dom.refAccordionList.appendChild(refItem);
    };

    if (cm.primary_reference) {
        addDocReference(cm.primary_reference, true);
    }
    
    if (cm.secondary_references && cm.secondary_references.length > 0) {
        cm.secondary_references.forEach(sec => addDocReference(sec, false));
    }

    if (!cm.primary_reference && (!cm.secondary_references || cm.secondary_references.length === 0)) {
        dom.refAccordionList.innerHTML = `
            <div class="empty-details-msg" style="padding: 24px; text-align: center; color: var(--text-muted);">
                매칭된 선행기술 문헌이 없습니다.
            </div>
        `;
    }
}
