/**
 * docconv Web UI 客户端 — 原生 JS，无框架。
 * 职责：文件上传、参数提交、任务轮询、结果下载、localStorage 最近任务。
 */

const API = '/api/v1';

// ---- 状态 ----
let selectedFile = null;
let activeJobId = null;
let pollingTimer = null;
let pollFailures = 0;
const POLL_INTERVAL_MS = 2000;
const POLL_BACKOFF_MS = 5000;
const DPI_MIN = 100;
const DPI_MAX = 400;
const CONCURRENCY_MIN = 1;
const CONCURRENCY_MAX = 5;

// ---- DOM 引用 ----
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const submitBtn = document.getElementById('submit-btn');
const optionsForm = document.getElementById('options-form');
const errorDisplay = document.getElementById('error-display');
const errorMessage = document.getElementById('error-message');
const jobPanel = document.getElementById('job-panel');
const jobIdEl = document.getElementById('job-id');
const jobStatusEl = document.getElementById('job-status');
const progressBar = document.getElementById('progress-bar');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const jobError = document.getElementById('job-error');
const jobErrorMsg = document.getElementById('job-error-message');
const resultActions = document.getElementById('result-actions');
const cancelAction = document.getElementById('cancel-action');
const recentJobsSection = document.getElementById('recent-jobs');
const recentJobsList = document.getElementById('recent-jobs-list');
const healthIndicator = document.getElementById('health-indicator');

// ---- 初始化 ----
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  setupDropZone();
  setupForm();
  setupResultActions();
  loadRecentJobs();
});

// ---- 健康检查 ----
async function checkHealth() {
  try {
    const resp = await fetch(`${API}/health`);
    if (resp.ok) {
      healthIndicator.textContent = '服务正常';
      healthIndicator.className = 'health-ok';
    } else {
      throw new Error('Service returned error');
    }
  } catch {
    healthIndicator.textContent = '服务不可用';
    healthIndicator.className = 'health-error';
  }
}

// ---- 拖拽上传 ----
function setupDropZone() {
  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  });
  fileInput.addEventListener('change', (e) => {
    if (e.target.files[0]) handleFileSelect(e.target.files[0]);
  });
}

function handleFileSelect(file) {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    showError('请选择 PDF 格式的文件');
    return;
  }
  if (file.size > 100 * 1024 * 1024) {
    showError('文件大小超过 100MB 限制');
    return;
  }
  selectedFile = file;
  fileInfo.textContent = `${file.name} (${formatSize(file.size)})`;
  submitBtn.disabled = false;
  hideError();
}

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---- 表单提交 ----
function setupForm() {
  optionsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!selectedFile) return;

    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';
    hideError();

    // 前端参数校验
    const dpiVal = parseInt(document.getElementById('dpi').value, 10);
    if (isNaN(dpiVal) || dpiVal < DPI_MIN || dpiVal > DPI_MAX) {
      showError('UI1002: DPI 必须在 100-400 之间');
      submitBtn.disabled = false;
      submitBtn.textContent = '开始转换';
      return;
    }
    const concurrencyVal = parseInt(document.getElementById('concurrency').value, 10);
    if (isNaN(concurrencyVal) || concurrencyVal < CONCURRENCY_MIN || concurrencyVal > CONCURRENCY_MAX) {
      showError('UI1002: 并发数必须在 1-5 之间');
      submitBtn.disabled = false;
      submitBtn.textContent = '开始转换';
      return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('model_profile', document.getElementById('model-profile').value);
    formData.append('dpi', document.getElementById('dpi').value);
    formData.append('concurrency', document.getElementById('concurrency').value);
    formData.append('instruction', document.getElementById('instruction').value);
    formData.append('no_cache', document.getElementById('no-cache').checked);
    formData.append('sensitive', document.getElementById('sensitive').checked);
    formData.append('dry_run', document.getElementById('dry-run').checked);

    try {
      const resp = await fetch(`${API}/jobs/upload`, {
        method: 'POST',
        body: formData,
      });
      const json = await resp.json();
      if (!resp.ok) {
        throw new Error(json.msg || json.message || `HTTP ${resp.status}`);
      }
      const job = json.data;
      activeJobId = job.job_id;
      jobIdEl.textContent = job.job_id;
      jobPanel.hidden = false;
      startPolling(job.job_id);
      saveRecentJob(job.job_id, selectedFile?.name || '');
    } catch (err) {
      showError(`提交失败: ${err.message}`);
      submitBtn.disabled = false;
      submitBtn.textContent = '开始转换';
    }
  });
}

// ---- 状态轮询 ----
function startPolling(jobId) {
  stopPolling();
  pollFailures = 0;
  jobError.hidden = true;
  resultActions.hidden = true;
  cancelAction.hidden = false;
  progressBar.hidden = false;

  pollingTimer = setInterval(() => pollJob(jobId), POLL_INTERVAL_MS);
  pollJob(jobId); // 立即查询一次
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

async function pollJob(jobId) {
  try {
    const resp = await fetch(`${API}/jobs/${jobId}`);
    const json = await resp.json();
    if (!resp.ok) throw new Error('Query failed');

    const job = json.data;
    updateJobStatus(job);

    if (job.status === 'succeeded' || job.status === 'failed' ||
        job.status === 'cancelled' || job.status === 'expired') {
      stopPolling();
      if (job.status === 'succeeded') {
        resultActions.hidden = false;
      } else {
        jobError.hidden = false;
        jobErrorMsg.textContent = job.error_message || '任务失败';
      }
      cancelAction.hidden = true;
      submitBtn.disabled = false;
      submitBtn.textContent = '开始转换';
    }
  } catch {
    pollFailures++;
    if (pollFailures >= 3) {
      clearInterval(pollingTimer);
      pollingTimer = setInterval(() => pollJob(jobId), POLL_BACKOFF_MS);
    }
  }
}

function updateJobStatus(job) {
  jobStatusEl.textContent = job.status;
  jobStatusEl.className = `status-badge status-${job.status}`;

  if (job.progress_json && typeof job.progress_json === 'object') {
    const p = job.progress_json;
    const pct = p.progress_percent || 0;
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${pct}%`;
    progressBar.hidden = false;
  } else if (job.status === 'running') {
    progressText.textContent = '处理中...';
    progressFill.style.width = '30%';
  } else if (job.status === 'queued') {
    progressText.textContent = '排队中...';
    progressFill.style.width = '10%';
  }
}

// ---- 结果操作 ----
function setupResultActions() {
  document.getElementById('download-md').addEventListener('click', () => {
    if (activeJobId) window.open(`${API}/jobs/${activeJobId}/result`, '_blank');
  });
  document.getElementById('download-report').addEventListener('click', () => {
    if (activeJobId) window.open(`${API}/jobs/${activeJobId}/report`, '_blank');
  });
  document.getElementById('new-job').addEventListener('click', resetUI);
  document.getElementById('cancel-job').addEventListener('click', async () => {
    if (!activeJobId) return;
    try {
      const resp = await fetch(`${API}/jobs/${activeJobId}/cancel`, { method: 'POST' });
      if (resp.ok) {
        stopPolling();
        jobStatusEl.textContent = 'cancelled';
        jobStatusEl.className = 'status-badge status-cancelled';
        cancelAction.hidden = true;
        submitBtn.disabled = false;
        submitBtn.textContent = '开始转换';
      } else {
        showError('取消任务失败');
      }
    } catch {
      showError('取消任务失败');
    }
  });
}

function resetUI() {
  stopPolling();
  selectedFile = null;
  activeJobId = null;
  fileInput.value = '';
  fileInfo.textContent = '';
  submitBtn.disabled = false;
  submitBtn.textContent = '开始转换';
  jobPanel.hidden = true;
  hideError();
}

// ---- 错误展示 ----
function showError(msg) {
  errorDisplay.hidden = false;
  errorMessage.textContent = msg;
}

function hideError() {
  errorDisplay.hidden = true;
  errorMessage.textContent = '';
}

// ---- 最近任务 (localStorage) ----
function loadRecentJobs() {
  try {
    const jobs = JSON.parse(localStorage.getItem('docconv.recentJobs') || '[]');
    if (jobs.length === 0) return;
    recentJobsSection.hidden = false;
    recentJobsList.innerHTML = '';
    jobs.slice(0, 10).forEach((j) => {
      const li = document.createElement('li');
      li.innerHTML = `<a onclick="loadJob('${j.id}')">${j.id.slice(-12)}</a><span>${j.name || ''}</span>`;
      recentJobsList.appendChild(li);
    });
  } catch { /* ignore parse error */ }
}

function saveRecentJob(id, name) {
  try {
    const jobs = JSON.parse(localStorage.getItem('docconv.recentJobs') || '[]');
    jobs.unshift({ id, name, ts: Date.now() });
    localStorage.setItem('docconv.recentJobs', JSON.stringify(jobs.slice(0, 50)));
  } catch { /* ignore quota error */ }
}

async function loadJob(jobId) {
  activeJobId = jobId;
  jobIdEl.textContent = jobId;
  jobPanel.hidden = false;
  startPolling(jobId);
}
