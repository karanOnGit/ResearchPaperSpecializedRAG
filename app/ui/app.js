/* ==========================================================================
   RESEARCH KNOWLEDGE ENGINE — CLIENT
   Interface logic: theming, motion, toasts, dialogue, the category-coded
   knowledge graph, OKF explorer and registry inspection.
   ========================================================================== */

let cy = null;
let graph3d = null;
let isGraph3DMode = true;
let isAutoRotating = false;
let rawGraphData = { nodes: [], edges: [] };
let activeCategoryFilter = null;
let highlighted3DNode = null;
let highlighted3DNeighbors = new Set();
let highlighted3DLinks = new Set();

let currentCitations = [];
let currentConcepts = [];
let currentProvenance = null;

const THEME_KEY = 'rke-theme';

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initTabs();
  initShortcuts();
  initIngestion();
  initResearchChat();
  initGraph();
  initOkfExplorer();
  initStorageInspector();
  initSettingsModal();
  initSideInspectorToggle();
  initSidebarExpandCollapse();
  refreshTelemetry();
});

/* ==================== Theme ==================== */
function initTheme() {
  // White paper is the house style; the inverted theme is opt-in and remembered.
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch (e) { /* storage unavailable */ }
  applyTheme(stored === 'dark' ? 'dark' : 'light');

  document.getElementById('themeToggleBtn')?.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  if (cy) cy.style(buildGraphStyle());
  if (graph3d) update3DTheme();
}

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* ==================== Typed-category encoding ==================== */
/* One hue per OKF category — mirrored by the graph, the legend and every chip.
   The backend may also emit Protocol / Theory / Dataset, so those are mapped
   too; anything unrecognised falls back to neutral. */
const CATEGORY_KEYS = ['architecture', 'mechanism', 'tool', 'entity', 'metric', 'protocol', 'theory', 'dataset'];

function categoryKey(category) {
  const k = String(category || '').trim().toLowerCase();
  return CATEGORY_KEYS.includes(k) ? k : 'unknown';
}

function categoryClass(category) {
  return `cat-${categoryKey(category)}`;
}

/* ==================== Toasts & confirm dialog ==================== */
function toast(title, desc = '', variant = 'info') {
  const stack = document.getElementById('toastStack');
  if (!stack) return;

  const icons = {
    info: 'ph-info',
    success: 'ph-check-circle',
    error: 'ph-warning-circle'
  };

  const el = document.createElement('div');
  el.className = `toast-item ${variant === 'error' ? 'toast-error' : ''}`;
  el.innerHTML = `
    <i class="ph-duotone ${icons[variant] || icons.info}" aria-hidden="true"></i>
    <div class="toast-copy">
      <div class="toast-title">${escapeHtml(title)}</div>
      ${desc ? `<div class="toast-desc">${escapeHtml(desc)}</div>` : ''}
    </div>
  `;
  stack.appendChild(el);

  const dismiss = () => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 260);
  };
  el.addEventListener('click', dismiss);
  setTimeout(dismiss, variant === 'error' ? 7000 : 4200);
}

function confirmDialog(message, { title = 'Are you sure?', confirmLabel = 'Confirm' } = {}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirmModal');
    if (!modal) { resolve(window.confirm(message)); return; }

    const titleEl = document.getElementById('confirmTitle');
    const msgEl = document.getElementById('confirmMessage');
    const okBtn = document.getElementById('confirmOkBtn');
    const cancelBtn = document.getElementById('confirmCancelBtn');

    if (titleEl) titleEl.textContent = title;
    if (msgEl) msgEl.textContent = message;
    if (okBtn) okBtn.textContent = confirmLabel;

    const close = (result) => {
      modal.classList.remove('open');
      okBtn?.removeEventListener('click', onOk);
      cancelBtn?.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onScrim);
      resolve(result);
    };
    const onOk = () => close(true);
    const onCancel = () => close(false);
    const onScrim = (e) => { if (e.target === modal) close(false); };

    okBtn?.addEventListener('click', onOk);
    cancelBtn?.addEventListener('click', onCancel);
    modal.addEventListener('click', onScrim);
    modal.classList.add('open');
    okBtn?.focus();
  });
}

/* Buttons carry an icon + label span; only swap the label. */
function setBtnLabel(btn, text) {
  if (!btn) return;
  const span = btn.querySelector('span');
  if (span) span.textContent = text;
  else btn.textContent = text;
}

/* ==================== Navigation ==================== */
function initTabs() {
  const tabs = document.querySelectorAll('.workstation-tab, .nav-tab');
  const panels = document.querySelectorAll('.tab-view, .tab-panel');

  const activateTab = (tab) => {
    const targetId = tab.getAttribute('data-tab');
    const targetPanel = document.getElementById(targetId);
    if (!targetPanel) return;

    tabs.forEach(t => t.classList.remove('active'));
    panels.forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    targetPanel.classList.add('active');

    // Keep the view bookmarkable / shareable
    if (location.hash !== `#${targetId}`) {
      history.replaceState(null, '', `#${targetId}`);
    }

    if (targetId === 'tab-graph') {
      setTimeout(() => {
        if (isGraph3DMode && graph3d) {
          const container = document.getElementById('graph3d');
          if (container && container.clientWidth > 0) {
            graph3d.width(container.clientWidth);
            graph3d.height(container.clientHeight);
          }
        } else if (cy) {
          cy.resize();
          cy.layout({ name: 'cose', animate: false }).run();
          cy.fit(undefined, 48);
        }
      }, 100);
    } else if (targetId === 'tab-storage') {
      const activeCol = document.querySelector('.store-tab.active')?.getAttribute('data-col') || 'col-docs';
      loadStorageData(activeCol);
    } else if (targetId === 'tab-okf') {
      loadOkfConcepts();
    }
  };

  tabs.forEach(tab => tab.addEventListener('click', () => activateTab(tab)));

  // Restore the view named in the URL fragment
  const initial = document.querySelector(`.workstation-tab[data-tab="${CSS.escape(location.hash.slice(1))}"]`);
  if (location.hash && initial) {
    activateTab(initial);
    // The fragment names a view, not a scroll anchor — keep the page at the top.
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    const toTop = () => window.scrollTo(0, 0);
    toTop();
    requestAnimationFrame(toTop);
    window.addEventListener('load', toTop, { once: true });
  }

  // Inspector segments (Citations / Concepts / Provenance)
  const segmentBtns = document.querySelectorAll('.segment-btn, .sub-tab');
  const segmentPanes = document.querySelectorAll('.inspector-pane, .sub-panel');
  segmentBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const subId = btn.getAttribute('data-sub');
      segmentBtns.forEach(b => b.classList.remove('active'));
      segmentPanes.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(subId)?.classList.add('active');
    });
  });
}

function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Cmd/Ctrl + 1..5 switches workstation view
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && /^[1-5]$/.test(e.key)) {
      const tabs = document.querySelectorAll('.workstation-tab');
      const target = tabs[parseInt(e.key, 10) - 1];
      if (target) { e.preventDefault(); target.click(); }
      return;
    }
    // Escape closes any open overlay
    if (e.key === 'Escape') {
      document.querySelectorAll('.enterprise-modal-scrim.open').forEach(m => {
        if (m.id === 'confirmModal') document.getElementById('confirmCancelBtn')?.click();
        else m.classList.remove('open');
      });
    }
  });
}

/* ==================== Telemetry & stats ==================== */
function animateCount(el, target) {
  if (!el) return;
  const to = Number(target) || 0;
  const from = Number(el.textContent.replace(/[^\d]/g, '')) || 0;
  if (from === to) { el.textContent = String(to); return; }
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    el.textContent = String(to);
    return;
  }

  const duration = 620;
  const start = performance.now();
  const step = (now) => {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = String(Math.round(from + (to - from) * eased));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

async function refreshTelemetry() {
  try {
    const res = await fetch('/api/storage/stats');
    if (!res.ok) return;
    const data = await res.json();
    const mongo = data.mongodb || {};
    const vec = data.vector_index || {};

    const mongoEl = document.getElementById('mongoStatusText');
    if (mongoEl) mongoEl.textContent = mongo.is_live_mongo ? 'MongoDB Atlas' : 'Embedded';

    animateCount(document.getElementById('vectorCountText'), vec.total_chunks || 0);
    animateCount(document.getElementById('conceptCountText'), mongo.counts?.concepts || 0);

    if (mongo.counts) {
      animateCount(document.getElementById('statDocs'), mongo.counts.documents || 0);
      animateCount(document.getElementById('statConcepts'), mongo.counts.concepts || 0);
      animateCount(document.getElementById('statRels'), mongo.counts.relationships || 0);
      animateCount(document.getElementById('statSources'), mongo.counts.sources || 0);
      animateCount(document.getElementById('statChunks'), vec.total_chunks || 0);
    }

    const badge = document.getElementById('activeModelBadge');
    if (badge && data.groq_model && !badge.classList.contains('badge-alert')) {
      badge.textContent = `Groq · ${data.groq_model}`;
    }
  } catch (err) {
    console.warn('Telemetry update failed', err);
  }
}

/* ==================== Ingestion lab ==================== */
function setPipelineState(state) {
  const strip = document.getElementById('pipelineStages');
  if (!strip) return;
  const stages = strip.querySelectorAll('.pipeline-stage');
  stages.forEach(s => s.classList.remove('running', 'done'));
  if (state === 'running') stages.forEach(s => s.classList.add('running'));
  else if (state === 'done') stages.forEach(s => s.classList.add('done'));
}

function initIngestion() {
  /* 1 · PDF (PyMuPDF) */
  const pdfDropZone = document.getElementById('pdfDropZone');
  const pdfFileInput = document.getElementById('pdfFileInput');
  const uploadPdfBtn = document.getElementById('uploadPdfBtn');
  const pdfSelectedName = document.getElementById('pdfSelectedName');
  let selectedPdfFile = null;

  const selectPdf = (file) => {
    selectedPdfFile = file;
    if (pdfSelectedName) pdfSelectedName.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
    if (uploadPdfBtn) uploadPdfBtn.disabled = false;
  };

  if (pdfDropZone && pdfFileInput) {
    pdfDropZone.addEventListener('click', () => pdfFileInput.click());
    pdfDropZone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pdfFileInput.click(); }
    });
    pdfFileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) selectPdf(e.target.files[0]);
    });
    pdfDropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      pdfDropZone.classList.add('dragover');
    });
    pdfDropZone.addEventListener('dragleave', () => pdfDropZone.classList.remove('dragover'));
    pdfDropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      pdfDropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) selectPdf(e.dataTransfer.files[0]);
    });
  }

  uploadPdfBtn?.addEventListener('click', async () => {
    if (!selectedPdfFile) return;
    uploadPdfBtn.disabled = true;
    setBtnLabel(uploadPdfBtn, 'Ingesting PDF…');
    setPipelineState('running');
    appendLog(`Extracting PDF "${selectedPdfFile.name}" with PyMuPDF layout parsing…`, 'info');

    const formData = new FormData();
    formData.append('file', selectedPdfFile);

    try {
      const res = await fetch('/api/ingest/pdf', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        appendLog(`Ingested "${data.title}" → ${data.chunks_count} chunks · ${data.concepts_count} OKF concepts · ${data.relationships_count} relationships.`, 'success');
        if (data.okf_export_path) appendLog(`OKF export written: ${data.okf_export_path}`, 'info');
        setPipelineState('done');
        toast('PDF ingested', `${data.title} · ${data.concepts_count} concepts extracted`, 'success');
        selectedPdfFile = null;
        if (pdfSelectedName) pdfSelectedName.textContent = '';
        if (pdfFileInput) pdfFileInput.value = '';
        uploadPdfBtn.disabled = true;
        refreshTelemetry();
        loadGraphData();
      } else {
        setPipelineState(null);
        appendLog(`PDF ingestion error: ${data.detail || 'Unknown error'}`, 'error');
        toast('PDF ingestion failed', data.detail || 'Unknown error', 'error');
      }
    } catch (err) {
      setPipelineState(null);
      appendLog(`PDF ingestion exception: ${err.message}`, 'error');
      toast('PDF ingestion failed', err.message, 'error');
    } finally {
      uploadPdfBtn.disabled = !selectedPdfFile;
      setBtnLabel(uploadPdfBtn, 'Ingest PDF Document');
    }
  });

  /* 2 · URL (Trafilatura) */
  const urlForm = document.getElementById('urlIngestForm');
  urlForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const urlInput = document.getElementById('urlInput');
    const crawlBtn = document.getElementById('crawlUrlBtn');
    const url = urlInput.value.trim();
    if (!url) return;

    crawlBtn.disabled = true;
    setBtnLabel(crawlBtn, 'Fetching…');
    setPipelineState('running');
    appendLog(`Fetching URL with Trafilatura web loader: ${url}`, 'info');

    try {
      const res = await fetch('/api/ingest/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (res.ok) {
        appendLog(`Ingested "${data.title}" → ${data.chunks_count} chunks · ${data.concepts_count} OKF concepts · ${data.relationships_count} relationships.`, 'success');
        setPipelineState('done');
        toast('URL ingested', data.title || url, 'success');
        urlInput.value = '';
        refreshTelemetry();
        loadGraphData();
      } else {
        setPipelineState(null);
        appendLog(`URL ingestion error: ${data.detail || 'Error'}`, 'error');
        toast('URL ingestion failed', data.detail || 'Error', 'error');
      }
    } catch (err) {
      setPipelineState(null);
      appendLog(`URL ingestion exception: ${err.message}`, 'error');
      toast('URL ingestion failed', err.message, 'error');
    } finally {
      crawlBtn.disabled = false;
      setBtnLabel(crawlBtn, 'Fetch & Ingest URL');
    }
  });

  /* 3 · Markdown / plain text, with file drop support */
  const textForm = document.getElementById('textIngestForm');
  const titleInput = document.getElementById('textTitleInput');
  const contentInput = document.getElementById('textContentInput');
  const saveBtn = document.getElementById('saveTextBtn');

  if (contentInput) {
    contentInput.addEventListener('dragover', (e) => {
      e.preventDefault();
      contentInput.style.borderColor = 'var(--border-strong)';
      contentInput.style.background = 'var(--bg-surface-active)';
    });
    contentInput.addEventListener('dragleave', () => {
      contentInput.style.borderColor = '';
      contentInput.style.background = '';
    });
    contentInput.addEventListener('drop', (e) => {
      e.preventDefault();
      contentInput.style.borderColor = '';
      contentInput.style.background = '';
      if (e.dataTransfer.files.length === 0) return;
      const file = e.dataTransfer.files[0];
      const reader = new FileReader();
      reader.onload = (event) => {
        contentInput.value = event.target.result;
        if (titleInput && !titleInput.value) titleInput.value = file.name.replace(/\.[^/.]+$/, '');
        appendLog(`Loaded local file "${file.name}" (${(file.size / 1024).toFixed(1)} KB) into the editor.`, 'info');
      };
      reader.readAsText(file);
    });
  }

  textForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = titleInput.value.trim();
    const content = contentInput.value.trim();
    if (!content) return;

    saveBtn.disabled = true;
    setBtnLabel(saveBtn, 'Processing…');
    setPipelineState('running');
    appendLog(`Ingesting markdown document "${title}"…`, 'info');

    try {
      const res = await fetch('/api/ingest/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
      });
      const data = await res.json();
      if (res.ok) {
        appendLog(`Ingested "${data.title}" → ${data.chunks_count} chunks · ${data.concepts_count} OKF concepts · ${data.relationships_count} relationships.`, 'success');
        setPipelineState('done');
        toast('Markdown ingested', `${data.title} · ${data.chunks_count} chunks`, 'success');
        titleInput.value = '';
        contentInput.value = '';
        refreshTelemetry();
        loadGraphData();
      } else {
        setPipelineState(null);
        appendLog(`Markdown ingestion error: ${data.detail || 'Error'}`, 'error');
        toast('Markdown ingestion failed', data.detail || 'Error', 'error');
      }
    } catch (err) {
      setPipelineState(null);
      appendLog(`Markdown ingestion exception: ${err.message}`, 'error');
      toast('Markdown ingestion failed', err.message, 'error');
    } finally {
      saveBtn.disabled = false;
      setBtnLabel(saveBtn, 'Ingest Markdown Text');
    }
  });

  document.getElementById('clearLogBtn')?.addEventListener('click', () => {
    const log = document.getElementById('ingestActivityLog');
    if (log) log.innerHTML = '<div class="console-entry info">Pipeline log cleared. Ready.</div>';
    setPipelineState(null);
  });
}

function appendLog(message, type = 'info') {
  const logContainer = document.getElementById('ingestActivityLog');
  if (!logContainer) return;
  const entry = document.createElement('div');
  entry.className = `console-entry ${type}`;
  entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  logContainer.appendChild(entry);
  logContainer.scrollTop = logContainer.scrollHeight;
}

/* ==================== Research dialogue ==================== */
function initResearchChat() {
  const form = document.getElementById('researchForm');
  const queryInput = document.getElementById('queryInput');
  const submitBtn = document.getElementById('submitQueryBtn');
  const messagesContainer = document.getElementById('chatMessages');

  if (!form || !queryInput) return;

  const autosize = () => {
    queryInput.style.height = 'auto';
    queryInput.style.height = Math.min(queryInput.scrollHeight, 180) + 'px';
  };
  queryInput.addEventListener('input', autosize);

  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit'));
    }
  });

  document.querySelectorAll('.prompt-suggestion').forEach(chip => {
    chip.addEventListener('click', () => {
      queryInput.value = chip.getAttribute('data-q') || '';
      autosize();
      queryInput.focus();
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    appendUserMessage(query);
    queryInput.value = '';
    queryInput.style.height = 'auto';
    if (submitBtn) submitBtn.disabled = true;

    const loadingCard = appendAssistantLoading();

    try {
      const res = await fetch('/api/research/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, session_id: 'active_session' })
      });
      const data = await res.json();

      if (res.ok) {
        updateAssistantCard(loadingCard, data);
        updateInspector(data);
      } else {
        renderSpeechError(loadingCard, `Synthesis error — ${data.detail || 'query failed'}`);
        toast('Synthesis failed', data.detail || 'Query failed', 'error');
      }
    } catch (err) {
      renderSpeechError(loadingCard, `Connection exception — ${err.message}`);
      toast('Connection error', err.message, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
      if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
      refreshTelemetry();
    }
  });
}

function renderSpeechError(card, message) {
  if (!card) return;
  const body = card.querySelector('.speech-body');
  const time = card.querySelector('.speech-time');
  if (time) time.textContent = 'Failed';
  if (body) {
    body.innerHTML = `
      <div class="thinking-row" style="color:var(--text-primary); font-weight:600;">
        <i class="ph-bold ph-warning-circle" aria-hidden="true"></i>
        <span>${escapeHtml(message)}</span>
      </div>
    `;
  }
}

function appendUserMessage(text) {
  const container = document.getElementById('chatMessages');
  if (!container) return;

  const card = document.createElement('div');
  card.className = 'speech-card user-speech';
  card.innerHTML = `
    <div class="speech-header">
      <div class="speaker-title">
        <i class="ph-bold ph-user" aria-hidden="true"></i>
        <span>Researcher</span>
      </div>
      <span class="speech-time">${new Date().toLocaleTimeString()}</span>
    </div>
    <div class="speech-body">
      <p>${escapeHtml(text)}</p>
    </div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

function appendAssistantLoading() {
  const container = document.getElementById('chatMessages');
  if (!container) return null;

  const card = document.createElement('div');
  card.className = 'speech-card assistant-speech';
  card.innerHTML = `
    <div class="speech-header">
      <div class="speaker-title">
        <i class="ph-bold ph-cube" aria-hidden="true"></i>
        <span>Research Knowledge Engine</span>
      </div>
      <span class="speech-time">Synthesising…</span>
    </div>
    <div class="speech-body academic-narrative">
      <div class="thinking-row">
        <span class="thinking-dots"><span></span><span></span><span></span></span>
        <span>Retrieving hybrid vectors &amp; concept relationships · Groq synthesis in progress</span>
      </div>
    </div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
  return card;
}

function updateAssistantCard(card, data) {
  if (!card) return;
  const timeEl = card.querySelector('.speech-time');
  if (timeEl) timeEl.textContent = new Date().toLocaleTimeString();

  const citations = data.citations || [];
  const concepts = data.related_concepts || [];
  const prov = data.confidence_provenance || {};
  const groundingPct = Math.round((prov.grounding_score ?? 0.95) * 100);
  const coveragePct = Math.round((prov.source_coverage ?? 1.0) * 100);
  const chunksCount = prov.retrieved_chunks || citations.length || 0;

  const citationsMap = new Map();
  citations.forEach(c => {
    citationsMap.set(c.citation_id, c);
  });

  let rawAnswer = data.answer || '';
  rawAnswer = rawAnswer.replace(/\[(\d+)\]/g, (match, p1) => {
    const citeId = parseInt(p1, 10);
    const citeObj = citationsMap.get(citeId);
    if (!citeObj) {
      return `<span class="inline-citation-badge" data-cite="${p1}">${p1}</span>`;
    }
    const safeQuote = escapeHtml(citeObj.quote || '');
    const safeTitle = escapeHtml(citeObj.source_title || 'Document');
    const safePage = citeObj.page ? `Page ${citeObj.page}` : 'Document excerpt';

    return `<span class="inline-citation-wrapper">
      <span class="inline-citation-badge" data-cite="${p1}">${p1}</span>
      <span class="citation-hover-popover" role="tooltip">
        <span class="popover-top-bar">
          <span class="popover-id-tag">Citation #${p1}</span>
          <span class="popover-page-tag">${safePage}</span>
        </span>
        <span class="popover-source-title" title="${safeTitle}">${safeTitle}</span>
        <span class="popover-quote-text">“${safeQuote}”</span>
      </span>
    </span>`;
  });

  const parsedHtml = (typeof marked !== 'undefined') ? marked.parse(rawAnswer) : `<p>${escapeHtml(rawAnswer)}</p>`;

  let sourcesHtml = '';
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `
      <div class="sources-consulted-bar">
        <span>Sources consulted · ${data.sources.length}</span>
        ${data.sources.map(s => `<span class="source-pill-token" title="${escapeHtml(s.source_path_or_url || '')}">${escapeHtml(s.title || s.id)}</span>`).join('')}
      </div>
    `;
  }

  const popoverUid = 'pop_' + Math.random().toString(36).substring(2, 9);

  const auditHtml = `
    <div class="chat-audit-deck">
      <div class="chat-audit-trigger" tabindex="0" aria-haspopup="dialog">
        <div class="chat-audit-pill">
          <i class="ph-duotone ph-shield-check chat-audit-icon" aria-hidden="true"></i>
          <span class="chat-audit-title">Audit Object Inspector</span>
          <div class="chat-audit-quick-chips">
            <span class="audit-chip">${citations.length} Citations</span>
            <span class="audit-chip">${concepts.length} Concepts</span>
            <span class="audit-chip audit-score-chip">${groundingPct}% Grounded</span>
          </div>
          <span class="chat-audit-hint"><i class="ph ph-cursor"></i> Hover to inspect</span>
        </div>

        <!-- The Hover Popover: Displayed ONLY when hovering over .chat-audit-trigger -->
        <div class="chat-audit-popover-card" role="dialog" aria-label="Audit Object Inspector">
          <div class="audit-popover-head">
            <div class="audit-popover-title-group">
              <i class="ph-duotone ph-shield-check" aria-hidden="true"></i>
              <div>
                <div class="audit-popover-kicker">Audit Evidence &amp; Verification</div>
                <div class="audit-popover-heading">Object Inspector</div>
              </div>
            </div>
            <div class="audit-popover-score-box">
              <div class="audit-score-num">${groundingPct}%</div>
              <div class="audit-score-label">Grounding</div>
            </div>
          </div>

          <div class="audit-popover-tabs-bar">
            <button type="button" class="audit-popover-tab active" data-target-pane="${popoverUid}-cites">
              <i class="ph ph-quotes"></i> Citations (${citations.length})
            </button>
            <button type="button" class="audit-popover-tab" data-target-pane="${popoverUid}-concepts">
              <i class="ph ph-tag"></i> Concepts (${concepts.length})
            </button>
            <button type="button" class="audit-popover-tab" data-target-pane="${popoverUid}-prov">
              <i class="ph ph-shield-check"></i> Provenance
            </button>
          </div>

          <div class="audit-popover-content-area">
            <!-- Citations Pane -->
            <div class="audit-popover-pane active" id="${popoverUid}-cites">
              ${citations.length === 0 ? '<div class="audit-empty-note">No verbatim quotes cited for this turn.</div>' :
                citations.map(c => `
                  <div class="audit-evidence-entry">
                    <div class="evidence-top-meta">
                      <span class="evidence-idx-badge">[${c.citation_id}]</span>
                      <span class="evidence-doc-name" title="${escapeHtml(c.source_title || 'Document')}">${escapeHtml(c.source_title || 'Document')}</span>
                      ${c.page ? `<span class="evidence-page-pill">Page ${c.page}</span>` : ''}
                    </div>
                    <div class="evidence-quote-snippet">“${escapeHtml(c.quote || '')}”</div>
                  </div>
                `).join('')
              }
            </div>

            <!-- Concepts Pane -->
            <div class="audit-popover-pane" id="${popoverUid}-concepts">
              ${concepts.length === 0 ? '<div class="audit-empty-note">No typed OKF objects mapped to this query.</div>' :
                concepts.map(c => `
                  <div class="audit-concept-entry">
                    <div class="concept-entry-head">
                      <span class="concept-name-label">${escapeHtml(c.name)}</span>
                      ${c.type ? `<span class="concept-type-tag">${escapeHtml(c.type)}</span>` : ''}
                      ${c.relevance_score ? `<span class="concept-score-tag">${Math.round(c.relevance_score * 100)}% match</span>` : ''}
                    </div>
                    ${c.definition ? `<div class="concept-def-snippet">${escapeHtml(c.definition)}</div>` : ''}
                  </div>
                `).join('')
              }
            </div>

            <!-- Provenance Pane -->
            <div class="audit-popover-pane" id="${popoverUid}-prov">
              <div class="audit-provenance-grid">
                <div class="prov-metric-card">
                  <div class="prov-metric-label">Grounding Score</div>
                  <div class="prov-metric-val">${groundingPct}%</div>
                  <div class="prov-metric-sub">Synthesized from retrieved chunks</div>
                </div>
                <div class="prov-metric-card">
                  <div class="prov-metric-label">Source Coverage</div>
                  <div class="prov-metric-val">${coveragePct}%</div>
                  <div class="prov-metric-sub">Evidence documents matched</div>
                </div>
                <div class="prov-metric-card">
                  <div class="prov-metric-label">Retrieved Chunks</div>
                  <div class="prov-metric-val">${chunksCount}</div>
                  <div class="prov-metric-sub">Hybrid vector + keyword matches</div>
                </div>
                <div class="prov-metric-card">
                  <div class="prov-metric-label">OKF Schema</div>
                  <div class="prov-metric-val">${escapeHtml(prov.okf_version || 'v1.0')}</div>
                  <div class="prov-metric-sub">Dual-indexed (Mongo + Chroma)</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  const bodyEl = card.querySelector('.speech-body');
  if (!bodyEl) return;
  bodyEl.innerHTML = `<div class="academic-narrative">${parsedHtml}</div>${sourcesHtml}${auditHtml}`;

  // Hook tab switching inside the in-chat hover popover
  bodyEl.querySelectorAll('.audit-popover-tab').forEach(tabBtn => {
    tabBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const targetPaneId = tabBtn.getAttribute('data-target-pane');
      const parentCard = tabBtn.closest('.chat-audit-popover-card');
      if (!parentCard) return;

      parentCard.querySelectorAll('.audit-popover-tab').forEach(b => b.classList.remove('active'));
      parentCard.querySelectorAll('.audit-popover-pane').forEach(p => p.classList.remove('active'));

      tabBtn.classList.add('active');
      const targetPane = parentCard.querySelector('#' + targetPaneId);
      if (targetPane) targetPane.classList.add('active');
    });
  });

  bodyEl.querySelectorAll('.inline-citation-badge').forEach(badge => {
    badge.addEventListener('click', () => highlightCitation(parseInt(badge.getAttribute('data-cite'), 10)));
  });
}

function initSideInspectorToggle() {
  const toggleBtn = document.getElementById('toggleSideInspectorBtn');
  const layout = document.querySelector('.studio-layout');
  const label = document.getElementById('toggleSideInspectorLabel');
  if (!toggleBtn || !layout) return;

  toggleBtn.addEventListener('click', () => {
    const isCollapsed = layout.classList.toggle('side-inspector-collapsed');
    if (label) {
      label.textContent = isCollapsed ? 'Show Inspector' : 'Side Inspector';
    }
  });
}

function initSidebarExpandCollapse() {
  const sidebarTrack = document.getElementById('sidebarTrack');
  const sidebarNav = document.getElementById('sidebarNav');
  const pinBtn = document.getElementById('pinSidebarBtn');
  if (!sidebarTrack || !sidebarNav) return;

  const PIN_KEY = 'rke-sidebar-pinned';
  let isPinned = false;
  try {
    isPinned = localStorage.getItem(PIN_KEY) === 'true';
  } catch (e) {}

  const applyPinState = (pinned) => {
    isPinned = pinned;
    sidebarTrack.classList.toggle('is-pinned', pinned);
    sidebarNav.classList.toggle('is-pinned', pinned);
    if (pinBtn) {
      pinBtn.classList.toggle('pinned', pinned);
      pinBtn.title = pinned ? 'Unpin sidebar (collapse to hover mode)' : 'Pin sidebar open';
    }
    try {
      localStorage.setItem(PIN_KEY, pinned ? 'true' : 'false');
    } catch (e) {}
  };

  if (isPinned) {
    applyPinState(true);
  }

  if (pinBtn) {
    pinBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      applyPinState(!isPinned);
      toast(isPinned ? 'Sidebar pinned' : 'Sidebar in hover mode', isPinned ? 'Expanded' : 'Hover to expand', 'info');
    });
  }
}
function updateInspector(data) {
  currentCitations = data.citations || [];
  currentConcepts = data.related_concepts || [];
  currentProvenance = data.confidence_provenance || null;

  /* Citations */
  const citationsList = document.getElementById('citationsList');
  if (citationsList) {
    citationsList.innerHTML = currentCitations.length === 0
      ? emptyState('ph-book-open-text', 'No direct citations', 'No verbatim quotes were linked to this synthesis turn.')
      : currentCitations.map(c => `
        <div class="citation-evidence-box" id="citationCard-${c.citation_id}">
          <div class="evidence-source-header">
            <span class="evidence-cite-badge">${c.citation_id}</span>
            <span class="evidence-title-text" title="${escapeHtml(c.source_title)}">${escapeHtml(c.source_title || 'Document')}</span>
          </div>
          <div class="verbatim-quote-box">${escapeHtml(c.quote)}</div>
          <div class="citation-meta-line">${c.page ? `Page ${c.page}` : 'Document chunk excerpt'}</div>
        </div>
      `).join('');
  }

  /* Related concepts */
  const conceptsList = document.getElementById('relatedConceptsList');
  if (conceptsList) {
    conceptsList.innerHTML = currentConcepts.length === 0
      ? emptyState('ph-tag', 'No concepts linked', 'No structured OKF concepts matched this inquiry.')
      : currentConcepts.map(c => `
        <div class="concept-registry-card ${categoryClass(c.category)}">
          <div class="concept-card-top">
            <span class="concept-label-name">${escapeHtml(c.name)}</span>
            <span class="concept-category-tag ${categoryClass(c.category)}">${escapeHtml(c.category || 'Entity')}</span>
          </div>
          <div class="concept-definition-body">${escapeHtml(c.definition || 'No definition recorded.')}</div>
        </div>
      `).join('');
  }

  /* Confidence & provenance */
  const provContainer = document.getElementById('provenanceContainer');
  if (provContainer) {
    if (currentProvenance) {
      const pct = Math.round((currentProvenance.score || 0) * 100);
      provContainer.innerHTML = `
        <div class="provenance-evidence-card">
          <div class="provenance-score-gauge">
            <div>
              <div class="provenance-gauge-label">Grounding confidence</div>
              <div class="score-number-display">${pct}<span style="font-size:1.2rem;">%</span></div>
            </div>
            <span class="grounding-rating-pill">${escapeHtml(currentProvenance.rating)}</span>
          </div>
          <div class="score-meter-track"><div class="score-meter-fill" style="width:${pct}%"></div></div>
          <div class="provenance-narrative">${escapeHtml(currentProvenance.rationale)}</div>
          <div class="provenance-meta-row"><span>Sources consulted</span><span>${currentProvenance.sources_consulted}</span></div>
          <div class="provenance-meta-row"><span>Concepts linked</span><span>${currentProvenance.concepts_linked}</span></div>
        </div>
      `;
    } else {
      provContainer.innerHTML = emptyState('ph-shield-check', 'Provenance ready', 'Submit a research question to compute grounding metrics.');
    }
  }
}

function emptyState(icon, heading, desc) {
  return `
    <div class="zero-data-state">
      <div class="zero-state-icon"><i class="ph-thin ${icon}" aria-hidden="true"></i></div>
      <div class="zero-state-heading">${escapeHtml(heading)}</div>
      <div class="zero-state-desc">${escapeHtml(desc)}</div>
    </div>
  `;
}

function highlightCitation(citeId) {
  document.querySelector('.segment-btn[data-sub="sub-citations"], .sub-tab[data-sub="sub-citations"]')?.click();

  const el = document.getElementById(`citationCard-${citeId}`);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.style.borderColor = 'var(--border-strong)';
  el.style.boxShadow = 'var(--shadow-glow)';
  el.style.transform = 'translateX(4px)';
  setTimeout(() => {
    el.style.borderColor = '';
    el.style.boxShadow = '';
    el.style.transform = '';
  }, 2400);
}

/* ==================== Knowledge graph ==================== */
function buildGraphStyle() {
  const ink = cssVar('--text-primary', '#000');
  const canvas = cssVar('--bg-void', '#fff');
  const edge = cssVar('--border-medium', 'rgba(0,0,0,.26)');
  const hue = key => cssVar(`--cat-${key}`, '#52525b');
  const sheer = key => cssVar(`--cat-${key}-sheer`, '#ececef');

  // Category → [cytoscape shape]. Shape doubles the encoding so the graph
  // stays readable without relying on colour alone.
  const shapes = {
    architecture: 'round-rectangle',
    mechanism: 'hexagon',
    tool: 'diamond',
    entity: 'ellipse',
    metric: 'triangle',
    protocol: 'round-tag',
    theory: 'octagon',
    dataset: 'barrel',
    unknown: 'ellipse'
  };

  const categoryRules = Object.keys(shapes)
    .filter(k => k !== 'unknown')
    .map(key => ({
      // Category strings arrive title-cased from the extractor
      selector: `node[category @= "${key}"]`,
      style: {
        'background-color': sheer(key),
        'border-color': hue(key),
        'shape': shapes[key]
      }
    }));

  return [
    {
      selector: 'node',
      style: {
        'label': 'data(label)',
        'color': ink,
        'font-family': 'Inter Tight, sans-serif',
        'font-size': '10px',
        'font-weight': 600,
        'text-valign': 'bottom',
        'text-margin-y': 7,
        'width': 'mapData(mention_count, 1, 10, 26, 54)',
        'height': 'mapData(mention_count, 1, 10, 26, 54)',
        'border-width': 2,
        'background-color': sheer('unknown'),
        'border-color': hue('unknown'),
        'shape': 'ellipse',
        'text-outline-color': canvas,
        'text-outline-width': 2.5,
        'transition-property': 'background-color, border-color, border-width, opacity',
        'transition-duration': '220ms'
      }
    },
    ...categoryRules,
    {
      selector: 'edge',
      style: {
        'width': 1.2,
        'line-color': edge,
        'target-arrow-color': edge,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-family': 'JetBrains Mono, monospace',
        'font-size': '8px',
        'letter-spacing': 0.4,
        'color': cssVar('--text-muted', '#5f5f66'),
        'text-rotation': 'autorotate',
        'text-outline-color': canvas,
        'text-outline-width': 2
      }
    },
    { selector: 'node:selected', style: { 'border-width': 4, 'border-color': ink } },
    { selector: 'edge:selected', style: { 'line-color': ink, 'target-arrow-color': ink, 'width': 2 } },
    { selector: 'node.dimmed', style: { 'opacity': 0.22 } },
    { selector: 'edge.dimmed', style: { 'opacity': 0.10 } },
    // Label density is managed by updateLabelDensity() so a dense graph stays readable
    { selector: 'node.label-muted', style: { 'text-opacity': 0 } },
    { selector: 'edge.label-muted', style: { 'text-opacity': 0 } },
    { selector: '.label-forced', style: { 'text-opacity': 1, 'z-index': 99 } }
  ];
}

/* Only label what can be read: every node when zoomed in or the graph is small,
   otherwise the most-mentioned concepts, plus whatever is hovered or focused. */
let labelThreshold = 2;

let labelFrame = null;

function updateLabelDensity() {
  if (!cy) return;
  if (labelFrame) cancelAnimationFrame(labelFrame);
  labelFrame = requestAnimationFrame(() => {
    labelFrame = null;
    const zoom = cy.zoom() || 1;
    const showAllNodes = zoom >= 0.75 || cy.nodes().length <= 40;
    const showEdges = zoom >= 1.15;

    // Model units scale with zoom, so divide to keep labels a constant size
    // on screen — readable whether the graph is fitted or zoomed right in.
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const nodeFont = clamp(11 / zoom, 9, 44);
    const edgeFont = clamp(8.5 / zoom, 7, 32);
    const outline = clamp(2.5 / zoom, 1.5, 9);

    cy.batch(() => {
      cy.nodes()
        .style({ 'font-size': `${nodeFont}px`, 'text-outline-width': outline, 'text-margin-y': clamp(7 / zoom, 5, 26) })
        .forEach(n => {
          const keep = showAllNodes || (n.data('mention_count') || 1) >= labelThreshold || n.selected();
          n.toggleClass('label-muted', !keep);
        });
      cy.edges()
        .style({ 'font-size': `${edgeFont}px`, 'text-outline-width': clamp(2 / zoom, 1.2, 7) })
        .toggleClass('label-muted', !showEdges);
    });
  });
}

function computeLabelThreshold() {
  if (!cy) return;
  const counts = cy.nodes().map(n => n.data('mention_count') || 1).sort((a, b) => b - a);
  if (counts.length === 0) { labelThreshold = 2; return; }
  labelThreshold = Math.max(2, counts[Math.floor(counts.length * 0.2)] || 2);
}

function getNodeCategoryColor(category) {
  const k = categoryKey(category);
  return cssVar(`--cat-${k}`, '#a1a1aa');
}

function getGraph3DBackground() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  return isDark ? '#09090b' : '#fcfcfd';
}

function update3DTheme() {
  if (!graph3d) return;
  graph3d.backgroundColor(getGraph3DBackground());
  graph3d.nodeColor(graph3d.nodeColor());
  graph3d.linkColor(graph3d.linkColor());
  graph3d.nodeThreeObject(graph3d.nodeThreeObject());
}

function init3DGraph() {
  const container = document.getElementById('graph3d');
  if (!container || typeof ForceGraph3D === 'undefined') return;

  graph3d = ForceGraph3D({ controlType: 'orbit' })(container)
    .backgroundColor(getGraph3DBackground())
    .nodeId('id')
    .nodeVal(node => Math.max(2.5, Math.sqrt(node.mention_count || 1) * 2.4))
    .nodeResolution(24)
    .nodeColor(node => {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      if (activeCategoryFilter) {
        if (categoryKey(node.category) === activeCategoryFilter) {
          return getNodeCategoryColor(node.category);
        }
        return isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
      }
      if (highlighted3DNode) {
        if (node.id === highlighted3DNode.id || highlighted3DNeighbors.has(node.id)) {
          return getNodeCategoryColor(node.category);
        }
        return isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
      }
      return getNodeCategoryColor(node.category);
    })
    .nodeLabel(node => {
      const color = getNodeCategoryColor(node.category);
      return `<div class="graph3d-tooltip">
        <div class="tooltip-title">${escapeHtml(node.label || node.id)}</div>
        <div class="tooltip-meta">
          <span class="tooltip-dot" style="background:${color}"></span>
          <span class="tooltip-cat">${escapeHtml(node.category || 'Entity')}</span>
          <span class="tooltip-sep">·</span>
          <span class="tooltip-mentions">${node.mention_count || 1} mentions</span>
        </div>
        ${node.definition ? `<div class="tooltip-def">${escapeHtml(node.definition.slice(0, 140))}${node.definition.length > 140 ? '…' : ''}</div>` : ''}
      </div>`;
    })
    .nodeThreeObjectExtend(true)
    .nodeThreeObject(node => {
      if (typeof SpriteText === 'undefined') return null;
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      const isProminent = (node.mention_count || 1) >= 2;
      const isFocus = highlighted3DNode && (node.id === highlighted3DNode.id || highlighted3DNeighbors.has(node.id));
      const isCatFilter = activeCategoryFilter && categoryKey(node.category) === activeCategoryFilter;

      if (!isProminent && !isFocus && !isCatFilter) return null;

      const sprite = new SpriteText(node.label || node.id);
      sprite.color = isDark ? '#ffffff' : '#0f172a';
      sprite.textHeight = Math.max(3.2, Math.min(6.5, Math.sqrt(node.mention_count || 1) * 1.8));
      sprite.fontFace = 'Inter Tight, -apple-system, BlinkMacSystemFont, sans-serif';
      sprite.fontWeight = '600';
      sprite.backgroundColor = isDark ? 'rgba(9, 9, 11, 0.78)' : 'rgba(255, 255, 255, 0.86)';
      sprite.borderColor = getNodeCategoryColor(node.category);
      sprite.borderWidth = 0.6;
      sprite.borderRadius = 3;
      sprite.padding = 2;
      const radius = Math.max(2.5, Math.sqrt(node.mention_count || 1) * 2.4);
      sprite.position.y = -(radius + 3.2);
      return sprite;
    })
    .linkSource('source')
    .linkTarget('target')
    .linkColor(link => {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      const sId = typeof link.source === 'object' ? link.source.id : link.source;
      const tId = typeof link.target === 'object' ? link.target.id : link.target;
      if (highlighted3DNode) {
        const isConnected = (sId === highlighted3DNode.id || tId === highlighted3DNode.id);
        return isConnected
          ? (isDark ? '#818cf8' : '#4f46e5')
          : (isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)');
      }
      return isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.16)';
    })
    .linkWidth(link => {
      if (highlighted3DNode) {
        const sId = typeof link.source === 'object' ? link.source.id : link.source;
        const tId = typeof link.target === 'object' ? link.target.id : link.target;
        return (sId === highlighted3DNode.id || tId === highlighted3DNode.id) ? 2.5 : 0.8;
      }
      return 1.2;
    })
    .linkDirectionalParticles(link => {
      if (highlighted3DNode) {
        const sId = typeof link.source === 'object' ? link.source.id : link.source;
        const tId = typeof link.target === 'object' ? link.target.id : link.target;
        return (sId === highlighted3DNode.id || tId === highlighted3DNode.id) ? 4 : 0;
      }
      return 2;
    })
    .linkDirectionalParticleWidth(1.8)
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleColor(() => {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      return isDark ? '#a78bfa' : '#6366f1';
    })
    .linkLabel(link => `<div class="graph3d-link-tooltip"><strong>${escapeHtml(link.label || 'CONNECTED_TO')}</strong>${link.description ? `<p style="margin:2px 0 0 0;font-size:0.65rem;color:var(--text-muted);">${escapeHtml(link.description)}</p>` : ''}</div>`)
    .onNodeClick(node => {
      handle3DNodeClick(node);
    })
    .onBackgroundClick(() => {
      clear3DHighlight();
    });

  const controls = graph3d.controls();
  if (controls) {
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.8;
    controls.zoomSpeed = 1.0;
  }

  // Force simulation parameters
  graph3d.d3Force('charge')?.strength(-110);
  graph3d.d3Force('link')?.distance(48);

  // ResizeObserver for container resizing
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const cr = entry.contentRect;
        if (cr.width > 0 && cr.height > 0 && graph3d) {
          graph3d.width(cr.width);
          graph3d.height(cr.height);
        }
      }
    });
    ro.observe(container);
  }
}

function handle3DNodeClick(node) {
  highlighted3DNode = node;
  highlighted3DNeighbors.clear();
  highlighted3DLinks.clear();

  const data = graph3d.graphData();
  data.links.forEach(l => {
    const sId = typeof l.source === 'object' ? l.source.id : l.source;
    const tId = typeof l.target === 'object' ? l.target.id : l.target;
    if (sId === node.id) {
      highlighted3DNeighbors.add(tId);
      highlighted3DLinks.add(l);
    } else if (tId === node.id) {
      highlighted3DNeighbors.add(sId);
      highlighted3DLinks.add(l);
    }
  });

  graph3d
    .nodeColor(graph3d.nodeColor())
    .linkColor(graph3d.linkColor())
    .linkWidth(graph3d.linkWidth())
    .linkDirectionalParticles(graph3d.linkDirectionalParticles())
    .nodeThreeObject(graph3d.nodeThreeObject());

  // Aim camera smoothly at node
  const distance = 90;
  const distRatio = 1 + distance / (Math.hypot(node.x, node.y, node.z) || 1);
  graph3d.cameraPosition(
    { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
    node,
    1100
  );

  showNodeDetails(node);
}

function clear3DHighlight() {
  if (!highlighted3DNode && !activeCategoryFilter) return;
  highlighted3DNode = null;
  highlighted3DNeighbors.clear();
  highlighted3DLinks.clear();
  activeCategoryFilter = null;
  document.querySelectorAll('.legend-chip').forEach(c => c.classList.remove('active'));

  if (graph3d) {
    graph3d
      .nodeColor(graph3d.nodeColor())
      .linkColor(graph3d.linkColor())
      .linkWidth(graph3d.linkWidth())
      .linkDirectionalParticles(graph3d.linkDirectionalParticles())
      .nodeThreeObject(graph3d.nodeThreeObject());
  }
}

function toggleAutoRotate() {
  if (!graph3d) return;
  const controls = graph3d.controls();
  if (!controls) return;

  isAutoRotating = !isAutoRotating;
  controls.autoRotate = isAutoRotating;
  controls.autoRotateSpeed = 1.2;

  const btn = document.getElementById('autoRotateGraphBtn');
  const label = document.getElementById('autoRotateLabel');
  const icon = btn?.querySelector('i');
  if (btn) btn.classList.toggle('active', isAutoRotating);
  if (label) label.textContent = isAutoRotating ? 'Rotating' : 'Auto-Rotate';
  if (icon) {
    icon.className = isAutoRotating ? 'ph-fill ph-pause-circle' : 'ph ph-play-circle';
  }
}

function toggleDimensionView(mode) {
  isGraph3DMode = (mode === '3d');
  const btn3D = document.getElementById('btnGraph3D');
  const btn2D = document.getElementById('btnGraph2D');
  const view3D = document.getElementById('graph3d');
  const view2D = document.getElementById('cy');
  const autoRotateBtn = document.getElementById('autoRotateGraphBtn');
  const hintBar = document.getElementById('graphHintBar');

  if (isGraph3DMode) {
    btn3D?.classList.add('active');
    btn2D?.classList.remove('active');
    if (view3D) view3D.style.display = 'block';
    if (view2D) view2D.style.display = 'none';
    if (autoRotateBtn) autoRotateBtn.style.display = 'inline-flex';
    if (hintBar) {
      hintBar.innerHTML = '<i class="ph ph-hand-pointing" aria-hidden="true"></i> Left-click drag to orbit · Right-click drag to pan · Scroll to zoom · Click node to inspect &amp; focus';
    }
    setTimeout(() => {
      if (graph3d && view3D) {
        graph3d.width(view3D.clientWidth);
        graph3d.height(view3D.clientHeight);
      }
    }, 60);
  } else {
    btn2D?.classList.add('active');
    btn3D?.classList.remove('active');
    if (view3D) view3D.style.display = 'none';
    if (view2D) view2D.style.display = 'block';
    if (autoRotateBtn) autoRotateBtn.style.display = 'none';
    if (hintBar) {
      hintBar.innerHTML = '<i class="ph ph-hand-pointing" aria-hidden="true"></i> Drag to pan · Scroll to zoom · Tap a node to inspect';
    }
    setTimeout(() => {
      if (cy) {
        cy.resize();
        cy.fit(undefined, 48);
      }
    }, 60);
  }
}

function resetGraphView() {
  if (isGraph3DMode && graph3d) {
    clear3DHighlight();
    graph3d.cameraPosition({ x: 0, y: 0, z: 320 }, { x: 0, y: 0, z: 0 }, 1000);
  } else if (cy) {
    cy.elements().removeClass('dimmed').removeClass('label-forced');
    cy.layout({ name: 'cose', animate: true, animationDuration: 600, padding: 48 }).run();
  }
}

function initGraph() {
  const cyContainer = document.getElementById('cy');
  if (cyContainer && typeof cytoscape !== 'undefined') {
    cy = cytoscape({
      container: cyContainer,
      elements: [],
      style: buildGraphStyle(),
      layout: { name: 'cose', animate: false },
      wheelSensitivity: 0.22,
      minZoom: 0.2,
      maxZoom: 3
    });

    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      cy.elements().addClass('dimmed');
      node.closedNeighborhood().removeClass('dimmed').addClass('label-forced');
      showNodeDetails(node.data());
    });
    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        cy.elements().removeClass('dimmed').removeClass('label-forced');
        updateLabelDensity();
      }
    });

    cy.on('mouseover', 'node', (evt) => evt.target.closedNeighborhood().addClass('label-forced'));
    cy.on('mouseout', 'node', (evt) => evt.target.closedNeighborhood().removeClass('label-forced'));
    cy.on('zoom', updateLabelDensity);
  }

  // Initialize 3D Graph
  init3DGraph();

  // Dimension switch listeners
  document.getElementById('btnGraph3D')?.addEventListener('click', () => toggleDimensionView('3d'));
  document.getElementById('btnGraph2D')?.addEventListener('click', () => toggleDimensionView('2d'));

  // Graph actions
  document.getElementById('autoRotateGraphBtn')?.addEventListener('click', toggleAutoRotate);
  document.getElementById('resetGraphBtn')?.addEventListener('click', resetGraphView);
  document.getElementById('refreshGraphBtn')?.addEventListener('click', loadGraphData);

  // Category legend chip click filtering
  document.querySelectorAll('.legend-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const text = chip.textContent.trim().toLowerCase();
      const catKey = categoryKey(text);
      if (activeCategoryFilter === catKey) {
        activeCategoryFilter = null;
        chip.classList.remove('active');
      } else {
        document.querySelectorAll('.legend-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        activeCategoryFilter = catKey;
      }
      if (isGraph3DMode && graph3d) {
        graph3d.nodeColor(graph3d.nodeColor()).nodeThreeObject(graph3d.nodeThreeObject());
      } else if (cy) {
        if (!activeCategoryFilter) {
          cy.elements().removeClass('dimmed');
        } else {
          cy.elements().addClass('dimmed');
          cy.nodes(`[category @= "${activeCategoryFilter}"]`).removeClass('dimmed').addClass('label-forced');
        }
      }
    });
  });

  loadGraphData();
}

async function loadGraphData() {
  try {
    const res = await fetch('/api/graph');
    if (!res.ok) return;
    const data = await res.json();
    rawGraphData = {
      nodes: data.nodes || [],
      edges: data.edges || []
    };

    // Update 3D Graph
    if (graph3d) {
      const gData = {
        nodes: (data.nodes || []).map(n => ({
          id: n.id,
          label: n.label,
          category: n.category,
          definition: n.definition,
          mention_count: n.mention_count || 1
        })),
        links: (data.edges || []).map(e => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          description: e.description,
          evidence: e.evidence
        }))
      };
      graph3d.graphData(gData);
    }

    // Update 2D Cytoscape
    if (cy) {
      const elements = [];
      (data.nodes || []).forEach(n => elements.push({
        group: 'nodes',
        data: {
          id: n.id,
          label: n.label,
          category: n.category,
          definition: n.definition,
          mention_count: n.mention_count || 1
        }
      }));

      (data.edges || []).forEach(e => elements.push({
        group: 'edges',
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          description: e.description,
          evidence: e.evidence
        }
      }));

      cy.elements().remove();
      cy.add(elements);
      cy.layout({ name: 'cose', animate: true, animationDuration: 700, padding: 48 }).run();
      computeLabelThreshold();
      updateLabelDensity();
    }

    const hasNodes = (data.nodes || []).length > 0;
    document.getElementById('graphEmptyState')?.classList.toggle('hidden', hasNodes);
  } catch (err) {
    console.warn('Failed to load graph data', err);
  }
}

function showNodeDetails(nodeData) {
  const titleEl = document.getElementById('selectedNodeName');
  const detailsEl = document.getElementById('selectedNodeDetails');
  if (titleEl) titleEl.textContent = nodeData.label || 'Concept';
  if (!detailsEl) return;

  const connectedEdges = (rawGraphData.edges || []).filter(
    e => e.source === nodeData.id || e.target === nodeData.id
  );

  let connectionsHtml = '';
  if (connectedEdges.length > 0) {
    const listItems = connectedEdges.slice(0, 15).map(e => {
      const isOut = e.source === nodeData.id;
      const otherId = isOut ? e.target : e.source;
      const relLabel = e.label || (isOut ? '→ CONNECTS' : '← LINKED_BY');
      return `
        <div class="connection-item-row" onclick="window.focusGraphNode('${escapeHtml(otherId)}')">
          <span class="connection-target-label" title="${escapeHtml(otherId)}">${escapeHtml(otherId)}</span>
          <span class="connection-rel-badge">${escapeHtml(relLabel)}</span>
        </div>
      `;
    }).join('');

    connectionsHtml = `
      <div class="node-connections-list">
        <div class="node-connections-heading">
          <span>Connected Concepts</span>
          <span class="badge">${connectedEdges.length}</span>
        </div>
        <div class="connections-items">${listItems}</div>
      </div>
    `;
  }

  detailsEl.innerHTML = `
    <div class="node-detail-row">
      <span class="concept-category-tag ${categoryClass(nodeData.category)}">${escapeHtml(nodeData.category || 'Entity')}</span>
      <span class="node-meta-mono">${nodeData.mention_count || 1} mentions</span>
    </div>
    <div class="node-definition-block">
      <strong>Definition</strong>
      <p>${escapeHtml(nodeData.definition || 'No definition recorded.')}</p>
    </div>
    ${connectionsHtml}
    <button class="btn-primary-action" id="viewOkfCardBtn">
      <i class="ph-bold ph-file-code" aria-hidden="true"></i><span>View OKF record</span>
    </button>
  `;
  document.getElementById('viewOkfCardBtn')?.addEventListener('click', () => inspectOkfFor(nodeData.id));
}

window.focusGraphNode = (nodeId) => {
  if (isGraph3DMode && graph3d) {
    const data = graph3d.graphData();
    const node = (data.nodes || []).find(n => n.id === nodeId);
    if (node) {
      handle3DNodeClick(node);
    }
  } else if (cy) {
    const cyNode = cy.getElementById(nodeId);
    if (cyNode && cyNode.length) {
      cy.elements().addClass('dimmed');
      cyNode.closedNeighborhood().removeClass('dimmed').addClass('label-forced');
      cy.animate({ center: { eles: cyNode }, zoom: 1.5 }, { duration: 600 });
      showNodeDetails(cyNode.data());
    }
  }
};

window.inspectOkfFor = (conceptId) => {
  document.querySelector('.workstation-tab[data-tab="tab-okf"], .nav-tab[data-tab="tab-okf"]')?.click();
  loadConceptOkf(conceptId);
};

/* ==================== OKF explorer ==================== */
function initOkfExplorer() {
  document.getElementById('copyOkfBtn')?.addEventListener('click', async () => {
    const textEl = document.getElementById('okfMarkdownContent');
    if (!textEl) return;
    try {
      await navigator.clipboard.writeText(textEl.innerText);
      toast('Copied', 'OKF Markdown + YAML is on your clipboard.', 'success');
    } catch (err) {
      toast('Copy failed', err.message, 'error');
    }
  });

  document.getElementById('filterConceptsInput')?.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    document.querySelectorAll('.okf-menu-item, .okf-item').forEach(item => {
      const head = item.querySelector('.okf-item-head, .okf-item-title');
      const name = head ? head.textContent.toLowerCase() : '';
      item.style.display = name.includes(term) ? 'block' : 'none';
    });
  });
}

async function loadOkfConcepts() {
  const listEl = document.getElementById('okfConceptsList');
  if (!listEl) return;

  try {
    const res = await fetch('/api/concepts');
    if (!res.ok) return;
    const concepts = await res.json();

    if (concepts.length === 0) {
      listEl.innerHTML = emptyState('ph-folder-open', 'No concepts loaded', 'Ingest a research document to extract typed OKF objects.');
      return;
    }

    listEl.innerHTML = concepts.map(c => `
      <div class="okf-menu-item ${categoryClass(c.category)}" data-id="${escapeHtml(c._id || c.name)}">
        <div class="okf-item-head">${escapeHtml(c.name)}</div>
        <div class="okf-item-caption"><span class="okf-cat-dot"></span>${escapeHtml(c.category || 'Entity')} · ${c.mention_count || 1} mentions</div>
      </div>
    `).join('');

    listEl.querySelectorAll('.okf-menu-item').forEach(item => {
      item.addEventListener('click', () => {
        listEl.querySelectorAll('.okf-menu-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        loadConceptOkf(item.getAttribute('data-id'));
      });
    });

    const firstItem = listEl.querySelector('.okf-menu-item');
    if (firstItem) {
      firstItem.classList.add('active');
      loadConceptOkf(concepts[0]._id || concepts[0].name);
    }
  } catch (err) {
    listEl.innerHTML = emptyState('ph-warning-circle', 'Load failed', err.message);
  }
}

async function loadConceptOkf(conceptId) {
  try {
    const res = await fetch(`/api/okf/concept/${encodeURIComponent(conceptId)}`);
    if (!res.ok) return;
    const data = await res.json();
    const titleEl = document.getElementById('okfPreviewTitle');
    const contentEl = document.getElementById('okfMarkdownContent');
    if (titleEl) titleEl.textContent = data.name;
    if (contentEl) contentEl.textContent = data.okf_markdown;
  } catch (err) {
    console.warn('Failed to load OKF for concept', err);
  }
}

/* ==================== Data registry ==================== */
function initStorageInspector() {
  const storeTabs = document.querySelectorAll('.store-tab');
  storeTabs.forEach(st => {
    st.addEventListener('click', () => {
      storeTabs.forEach(s => s.classList.remove('active'));
      st.classList.add('active');
      loadStorageData(st.getAttribute('data-col'));
    });
  });

  document.getElementById('refreshStorageBtn')?.addEventListener('click', () => {
    const activeCol = document.querySelector('.store-tab.active')?.getAttribute('data-col') || 'col-docs';
    loadStorageData(activeCol);
    refreshTelemetry();
  });

  document.getElementById('clearStorageBtn')?.addEventListener('click', async () => {
    const ok = await confirmDialog(
      'This permanently purges every ingested document, concept, relationship, source and vector chunk. It cannot be undone.',
      { title: 'Purge the knowledge base?', confirmLabel: 'Purge everything' }
    );
    if (!ok) return;

    try {
      const res = await fetch('/api/storage/clear', { method: 'POST' });
      if (res.ok) {
        toast('Knowledge base purged', 'All documents, concepts and embeddings were removed.', 'success');
        refreshTelemetry();
        loadGraphData();
        loadOkfConcepts();
        const activeCol = document.querySelector('.store-tab.active')?.getAttribute('data-col') || 'col-docs';
        loadStorageData(activeCol);
      } else {
        toast('Purge failed', `Server responded ${res.status}`, 'error');
      }
    } catch (err) {
      toast('Purge failed', err.message, 'error');
    }
  });
}

function loadingRow(cols, label) {
  return `<tr><td colspan="${cols}" class="table-loading-cell">${escapeHtml(label)}</td></tr>`;
}
function emptyRow(cols, icon, heading, desc) {
  return `<tr><td colspan="${cols}">${emptyState(icon, heading, desc)}</td></tr>`;
}
function errorRow(cols, message) {
  return `<tr><td colspan="${cols}" class="table-error-cell">${escapeHtml(message)}</td></tr>`;
}

async function loadStorageData(col) {
  const thead = document.getElementById('tableHeadRow');
  const tbody = document.getElementById('tableBody');
  if (!thead || !tbody) return;

  if (col === 'col-docs') {
    thead.innerHTML = '<th>Title</th><th>Type</th><th>Chunks</th><th>Concepts</th><th>Relationships</th><th>Created</th>';
    tbody.innerHTML = loadingRow(6, 'Querying documents…');
    try {
      const docs = await (await fetch('/api/documents')).json();
      tbody.innerHTML = docs.length === 0
        ? emptyRow(6, 'ph-files', 'No documents ingested', 'Upload a PDF, URL or Markdown file to populate the registry.')
        : docs.map(d => `
          <tr>
            <td><strong>${escapeHtml(d.title || d._id)}</strong></td>
            <td><span class="concept-category-tag">${escapeHtml(d.source_type || 'doc')}</span></td>
            <td class="table-mono-cell">${d.total_chunks || 0}</td>
            <td class="table-mono-cell">${d.total_concepts || 0}</td>
            <td class="table-mono-cell">${d.total_relationships || 0}</td>
            <td class="table-mono-cell">${escapeHtml(d.created_at || '')}</td>
          </tr>
        `).join('');
    } catch (e) {
      tbody.innerHTML = errorRow(6, `Error: ${e.message}`);
    }

  } else if (col === 'col-concepts') {
    thead.innerHTML = '<th>Concept</th><th>Category</th><th>Definition</th><th>Mentions</th>';
    tbody.innerHTML = loadingRow(4, 'Querying concepts…');
    try {
      const concepts = await (await fetch('/api/concepts')).json();
      tbody.innerHTML = concepts.length === 0
        ? emptyRow(4, 'ph-tag', 'No concepts stored', 'Extracted OKF concepts will be listed here.')
        : concepts.map(c => `
          <tr>
            <td><strong>${escapeHtml(c.name)}</strong></td>
            <td><span class="concept-category-tag ${categoryClass(c.category)}">${escapeHtml(c.category || 'Entity')}</span></td>
            <td class="table-note-cell">${escapeHtml(c.definition || '')}</td>
            <td class="table-mono-cell">${c.mention_count || 1}</td>
          </tr>
        `).join('');
    } catch (e) {
      tbody.innerHTML = errorRow(4, `Error: ${e.message}`);
    }

  } else if (col === 'col-rels') {
    thead.innerHTML = '<th>Source</th><th>Relation</th><th>Target</th><th>Description / evidence</th>';
    tbody.innerHTML = loadingRow(4, 'Querying relationships…');
    try {
      const rels = await (await fetch('/api/relationships')).json();
      tbody.innerHTML = rels.length === 0
        ? emptyRow(4, 'ph-tree-structure', 'No relationships stored', 'Graph edges extracted between concepts are catalogued here.')
        : rels.map(r => `
          <tr>
            <td><strong>${escapeHtml(r.source)}</strong></td>
            <td><span class="concept-category-tag">${escapeHtml(r.relation_type)}</span></td>
            <td><strong>${escapeHtml(r.target)}</strong></td>
            <td class="table-note-cell">${escapeHtml(r.description || r.evidence || '')}</td>
          </tr>
        `).join('');
    } catch (e) {
      tbody.innerHTML = errorRow(4, `Error: ${e.message}`);
    }

  } else if (col === 'col-sources') {
    thead.innerHTML = '<th>Title</th><th>Modality</th><th>URI / path</th><th>Chunks</th>';
    tbody.innerHTML = loadingRow(4, 'Querying sources…');
    try {
      const sources = await (await fetch('/api/sources')).json();
      tbody.innerHTML = sources.length === 0
        ? emptyRow(4, 'ph-archive', 'No sources tracked', 'Original files and URLs are indexed here.')
        : sources.map(s => `
          <tr>
            <td><strong>${escapeHtml(s.title || s.id)}</strong></td>
            <td><span class="concept-category-tag">${escapeHtml(s.source_type)}</span></td>
            <td class="table-mono-cell">${escapeHtml(s.source_path_or_url || '')}</td>
            <td class="table-mono-cell">${s.total_chunks || 0}</td>
          </tr>
        `).join('');
    } catch (e) {
      tbody.innerHTML = errorRow(4, `Error: ${e.message}`);
    }
  }
}

/* ==================== Settings ==================== */
/* The Groq key is supplied here, never baked into the repo. The model lists
   are fetched from Groq with that key, so you can only pick a model your
   account can actually serve. */
let modelCatalog = { models: [], available: false, reason: '' };

function fillModelSelect(selectEl, current, placeholder) {
  if (!selectEl) return;
  selectEl.innerHTML = '';

  if (!modelCatalog.available || modelCatalog.models.length === 0) {
    const opt = document.createElement('option');
    opt.value = current || '';
    opt.textContent = current || placeholder;
    selectEl.appendChild(opt);
    selectEl.disabled = true;
    return;
  }

  selectEl.disabled = false;
  const known = modelCatalog.models.some(m => m.id === current);
  if (current && !known) {
    // Keep an unavailable saved model visible so the mismatch is obvious
    const opt = document.createElement('option');
    opt.value = current;
    opt.textContent = `${current} — unavailable to this key`;
    selectEl.appendChild(opt);
  }
  modelCatalog.models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    const ctx = m.context_window ? ` · ${Math.round(m.context_window / 1024)}k ctx` : '';
    opt.textContent = `${m.id}${ctx}`;
    selectEl.appendChild(opt);
  });
  selectEl.value = current || modelCatalog.models[0].id;
}

async function loadModelCatalog(currentSynthesis, currentExtraction) {
  const hint = document.getElementById('modelCatalogHint');
  if (hint) hint.textContent = 'Loading models from Groq…';

  try {
    const res = await fetch('/api/settings/models');
    modelCatalog = await res.json();
  } catch (err) {
    modelCatalog = { models: [], available: false, reason: err.message };
  }

  fillModelSelect(document.getElementById('groqModelSelect'), currentSynthesis, 'Add an API key to load models');
  fillModelSelect(document.getElementById('extractionModelSelect'), currentExtraction, 'Add an API key to load models');

  if (hint) {
    hint.textContent = modelCatalog.available
      ? `${modelCatalog.models.length} chat models available to this key.`
      : modelCatalog.reason || 'Model list unavailable.';
  }
}

function describeKeyState(data, catalogStatus) {
  const hint = document.getElementById('apiKeyStatusHint');
  const removeBtn = document.getElementById('removeGroqKeyBtn');
  if (hint) {
    const where = {
      stored: 'saved on this machine',
      environment: 'from the environment',
      session: 'this session only'
    }[data.groq_api_key_source];

    if (!data.groq_api_key_set) {
      hint.textContent = 'No key set — extraction and synthesis are disabled';
      hint.classList.add('hint-alert');
    } else if (catalogStatus === 'rejected') {
      hint.textContent = `Rejected by Groq · ${data.groq_api_key_preview} — enter a current key`;
      hint.classList.add('hint-alert');
    } else {
      hint.textContent = `Active · ${data.groq_api_key_preview} · ${where || 'runtime'}`;
      hint.classList.remove('hint-alert');
    }
  }
  if (removeBtn) removeBtn.hidden = data.groq_api_key_source !== 'stored';
}

async function loadSettingsIntoModal() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return null;
    const data = await res.json();

    const uriInput = document.getElementById('mongoUriInput');
    if (uriInput) uriInput.value = (data.mongodb_uri && data.mongodb_uri.startsWith('mongodb')) ? data.mongodb_uri : '';

    describeKeyState(data, null);
    await loadModelCatalog(data.groq_model, data.extraction_model);
    describeKeyState(data, modelCatalog.status);
    return data;
  } catch (err) {
    console.warn('Failed to load settings', err);
    return null;
  }
}

function markKeyProblem(label) {
  const badge = document.getElementById('activeModelBadge');
  if (!badge) return;
  badge.classList.add('badge-alert');
  badge.textContent = label;
  badge.title = 'Open Engine Configuration to fix the Groq API key';
}

function initSettingsModal() {
  const modal = document.getElementById('settingsModal');
  const openBtn = document.getElementById('openSettingsBtn');
  const closeBtn = document.getElementById('closeSettingsBtn');
  const cancelBtn = document.getElementById('cancelSettingsBtn');
  const form = document.getElementById('settingsForm');

  if (!modal) return;

  const openModal = async () => {
    modal.classList.add('open');
    await loadSettingsIntoModal();
  };
  const closeModal = () => modal.classList.remove('open');

  openBtn?.addEventListener('click', openModal);
  closeBtn?.addEventListener('click', closeModal);
  cancelBtn?.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  // Re-read the catalog as soon as a key is pasted in
  document.getElementById('groqApiKeyInput')?.addEventListener('change', async (e) => {
    const key = e.target.value.trim();
    if (!key) return;
    const hint = document.getElementById('modelCatalogHint');
    if (hint) hint.textContent = 'Save the key to load its models.';
  });

  document.getElementById('removeGroqKeyBtn')?.addEventListener('click', async () => {
    const ok = await confirmDialog(
      'The stored Groq API key will be deleted from this machine. Extraction and synthesis stop working until you enter a new one.',
      { title: 'Remove the API key?', confirmLabel: 'Remove key' }
    );
    if (!ok) return;
    try {
      const res = await fetch('/api/settings/groq-key', { method: 'DELETE' });
      if (res.ok) {
        toast('API key removed', 'Enter a new key to resume extraction and synthesis.', 'success');
        await loadSettingsIntoModal();
        refreshTelemetry();
      } else {
        toast('Could not remove the key', `Server responded ${res.status}`, 'error');
      }
    } catch (err) {
      toast('Could not remove the key', err.message, 'error');
    }
  });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const saveBtn = document.getElementById('saveSettingsBtn');
    const groqKey = document.getElementById('groqApiKeyInput')?.value.trim();
    const model = document.getElementById('groqModelSelect')?.value;
    const extractionModel = document.getElementById('extractionModelSelect')?.value;
    const mongoUri = document.getElementById('mongoUriInput')?.value.trim();

    const payload = { mongodb_uri: mongoUri || '' };
    if (model) payload.groq_model = model;
    if (extractionModel) payload.extraction_model = extractionModel;
    if (groqKey) payload.groq_api_key = groqKey;

    if (saveBtn) { saveBtn.disabled = true; setBtnLabel(saveBtn, 'Saving…'); }

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        const keyInput = document.getElementById('groqApiKeyInput');
        if (keyInput) keyInput.value = '';
        toast('Settings saved', `Synthesis model: ${data.settings?.groq_model || model}`, 'success');
        if (groqKey) {
          // A new key means a new catalog — reload rather than close blind
          await loadSettingsIntoModal();
        } else {
          closeModal();
        }
        refreshTelemetry();
      } else {
        toast('Could not save settings', data.detail || `Server responded ${res.status}`, 'error');
      }
    } catch (err) {
      toast('Could not save settings', err.message, 'error');
    } finally {
      if (saveBtn) { saveBtn.disabled = false; setBtnLabel(saveBtn, 'Save settings'); }
    }
  });

  // Startup check: no key, or a key Groq refuses, means answers quietly fall
  // back to a non-LLM heuristic — so say so up front.
  (async () => {
    try {
      const data = await (await fetch('/api/settings')).json();
      if (!data.groq_api_key_set) {
        toast('Groq API key required', 'Add your key in Engine Configuration to enable extraction and synthesis.', 'error');
        openModal();
        return;
      }
      const catalog = await (await fetch('/api/settings/models')).json();
      if (catalog.status === 'rejected') {
        markKeyProblem('Key rejected');
        toast('Groq rejected the stored API key', 'Answers will fall back to non-LLM synthesis until you enter a current key.', 'error');
        openModal();
      } else if (catalog.status === 'unreachable') {
        markKeyProblem('Groq unreachable');
        toast('Could not reach Groq', catalog.reason || 'Model list unavailable.', 'error');
      }
    } catch (err) {
      console.warn('Settings preflight failed', err);
    }
  })();
}

/* ==================== Utilities ==================== */
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
