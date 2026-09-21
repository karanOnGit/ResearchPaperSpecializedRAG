// Research Knowledge Engine Client Application
// Enterprise Light Research Design System Logic

let cy = null;
let currentCitations = [];
let currentConcepts = [];
let currentProvenance = null;

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initIngestion();
  initResearchChat();
  initGraph();
  initOkfExplorer();
  initStorageInspector();
  initSettingsModal();
  refreshTelemetry();
});

// ==================== Navigation Tabs ====================
function initTabs() {
  const tabs = document.querySelectorAll('.workstation-tab, .nav-tab');
  const panels = document.querySelectorAll('.tab-view, .tab-panel');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('data-tab');
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add('active');
        if (targetId === 'tab-graph' && cy) {
          setTimeout(() => {
            cy.resize();
            cy.layout({ name: 'cose', animate: false }).run();
          }, 100);
        } else if (targetId === 'tab-storage') {
          const activeCol = document.querySelector('.store-tab.active')?.getAttribute('data-col') || 'col-docs';
          loadStorageData(activeCol);
        } else if (targetId === 'tab-okf') {
          loadOkfConcepts();
        }
      }
    });
  });

  // Inspector segment buttons (Citations / Concepts / Provenance)
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

// ==================== Telemetry & Stats ====================
async function refreshTelemetry() {
  try {
    const res = await fetch('/api/storage/stats');
    if (res.ok) {
      const data = await res.json();
      const mongo = data.mongodb || {};
      const vec = data.vector_index || {};

      const isLive = mongo.is_live_mongo;
      const mongoEl = document.getElementById('mongoStatusText');
      if (mongoEl) {
        mongoEl.textContent = isLive ? 'Live MongoDB Atlas' : 'Embedded Store';
      }
      const vecEl = document.getElementById('vectorCountText');
      if (vecEl) vecEl.textContent = vec.total_chunks || 0;
      const conceptEl = document.getElementById('conceptCountText');
      if (conceptEl) conceptEl.textContent = mongo.counts?.concepts || 0;

      // Update Data Registry metric cards
      if (mongo.counts) {
        const dEl = document.getElementById('statDocs');
        const cEl = document.getElementById('statConcepts');
        const rEl = document.getElementById('statRels');
        const sEl = document.getElementById('statSources');
        const chEl = document.getElementById('statChunks');

        if (dEl) dEl.textContent = mongo.counts.documents || 0;
        if (cEl) cEl.textContent = mongo.counts.concepts || 0;
        if (rEl) rEl.textContent = mongo.counts.relationships || 0;
        if (sEl) sEl.textContent = mongo.counts.sources || 0;
        if (chEl) chEl.textContent = vec.total_chunks || 0;
      }

      const badge = document.getElementById('activeModelBadge');
      if (badge && data.groq_model) {
        badge.textContent = `Groq: ${data.groq_model}`;
      }
    }
  } catch (err) {
    console.warn('Telemetry update failed', err);
  }
}

// ==================== Ingestion Hub ====================
function initIngestion() {
  // 1. PDF PyMuPDF Ingest
  const pdfDropZone = document.getElementById('pdfDropZone');
  const pdfFileInput = document.getElementById('pdfFileInput');
  const uploadPdfBtn = document.getElementById('uploadPdfBtn');
  const pdfSelectedName = document.getElementById('pdfSelectedName');
  let selectedPdfFile = null;

  if (pdfDropZone && pdfFileInput) {
    pdfDropZone.addEventListener('click', () => pdfFileInput.click());
    pdfFileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        selectedPdfFile = e.target.files[0];
        pdfSelectedName.textContent = `Selected: ${selectedPdfFile.name} (${(selectedPdfFile.size / 1024).toFixed(1)} KB)`;
        uploadPdfBtn.disabled = false;
      }
    });

    pdfDropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      pdfDropZone.classList.add('dragover');
    });
    pdfDropZone.addEventListener('dragleave', () => pdfDropZone.classList.remove('dragover'));
    pdfDropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      pdfDropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        selectedPdfFile = e.dataTransfer.files[0];
        pdfSelectedName.textContent = `Selected: ${selectedPdfFile.name} (${(selectedPdfFile.size / 1024).toFixed(1)} KB)`;
        uploadPdfBtn.disabled = false;
      }
    });
  }

  if (uploadPdfBtn) {
    uploadPdfBtn.addEventListener('click', async () => {
      if (!selectedPdfFile) return;
      uploadPdfBtn.disabled = true;
      uploadPdfBtn.textContent = 'Ingesting PDF...';
      appendLog(`Extracting PDF: "${selectedPdfFile.name}" with PyMuPDF layout parsing...`, 'info');

      const formData = new FormData();
      formData.append('file', selectedPdfFile);

      try {
        const res = await fetch('/api/ingest/pdf', { method: 'POST', body: formData });
        const data = await res.json();
        if (res.ok) {
          appendLog(`Successfully ingested PDF: "${data.title}" -> ${data.chunks_count} chunks, ${data.concepts_count} OKF concepts, ${data.relationships_count} relationships.`, 'success');
          if (data.okf_export_path) {
            appendLog(`OKF Export generated: ${data.okf_export_path}`, 'info');
          }
          selectedPdfFile = null;
          if (pdfSelectedName) pdfSelectedName.textContent = '';
          uploadPdfBtn.disabled = true;
          refreshTelemetry();
          loadGraphData();
        } else {
          appendLog(`PDF Ingestion Error: ${data.detail || 'Unknown error'}`, 'error');
        }
      } catch (err) {
        appendLog(`PDF Ingestion Exception: ${err.message}`, 'error');
      } finally {
        uploadPdfBtn.disabled = false;
        uploadPdfBtn.textContent = 'Ingest PDF Document';
      }
    });
  }

  // 2. URL Trafilatura Ingest
  const urlForm = document.getElementById('urlIngestForm');
  if (urlForm) {
    urlForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const urlInput = document.getElementById('urlInput');
      const crawlBtn = document.getElementById('crawlUrlBtn');
      const url = urlInput.value.trim();
      if (!url) return;

      crawlBtn.disabled = true;
      crawlBtn.textContent = 'Fetching & Extracting...';
      appendLog(`Fetching URL with Trafilatura Web Loader: ${url}`, 'info');

      try {
        const res = await fetch('/api/ingest/url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const data = await res.json();
        if (res.ok) {
          appendLog(`URL Ingestion Complete: "${data.title}" -> ${data.chunks_count} chunks, ${data.concepts_count} OKF concepts, ${data.relationships_count} relationships.`, 'success');
          urlInput.value = '';
          refreshTelemetry();
          loadGraphData();
        } else {
          appendLog(`URL Ingestion Error: ${data.detail || 'Error'}`, 'error');
        }
      } catch (err) {
        appendLog(`URL Ingestion Exception: ${err.message}`, 'error');
      } finally {
        crawlBtn.disabled = false;
        crawlBtn.textContent = 'Fetch & Ingest URL';
      }
    });
  }

  // 3. Markdown / Plain Text Ingest (with drag-and-drop file reading support)
  const textForm = document.getElementById('textIngestForm');
  const titleInput = document.getElementById('textTitleInput');
  const contentInput = document.getElementById('textContentInput');
  const saveBtn = document.getElementById('saveTextBtn');

  if (contentInput) {
    // Enable dragging and dropping .md or .txt files directly onto the textarea
    contentInput.addEventListener('dragover', (e) => {
      e.preventDefault();
      contentInput.style.borderColor = 'var(--accent-indigo)';
      contentInput.style.background = 'var(--accent-indigo-light)';
    });
    contentInput.addEventListener('dragleave', () => {
      contentInput.style.borderColor = '';
      contentInput.style.background = '';
    });
    contentInput.addEventListener('drop', (e) => {
      e.preventDefault();
      contentInput.style.borderColor = '';
      contentInput.style.background = '';
      if (e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        const reader = new FileReader();
        reader.onload = (event) => {
          contentInput.value = event.target.result;
          if (titleInput && !titleInput.value) {
            titleInput.value = file.name.replace(/\.[^/.]+$/, '');
          }
          appendLog(`Loaded local Markdown file "${file.name}" (${(file.size / 1024).toFixed(1)} KB) into editor.`, 'info');
        };
        reader.readAsText(file);
      }
    });
  }

  if (textForm) {
    textForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const title = titleInput.value.trim();
      const content = contentInput.value.trim();
      if (!content) return;

      saveBtn.disabled = true;
      saveBtn.textContent = 'Processing Markdown...';
      appendLog(`Ingesting Markdown Document: "${title}"...`, 'info');

      try {
        const res = await fetch('/api/ingest/text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content }),
        });
        const data = await res.json();
        if (res.ok) {
          appendLog(`Markdown Ingested: "${data.title}" -> ${data.chunks_count} chunks, ${data.concepts_count} OKF concepts, ${data.relationships_count} relationships.`, 'success');
          titleInput.value = '';
          contentInput.value = '';
          refreshTelemetry();
          loadGraphData();
        } else {
          appendLog(`Markdown Ingestion Error: ${data.detail || 'Error'}`, 'error');
        }
      } catch (err) {
        appendLog(`Markdown Ingestion Exception: ${err.message}`, 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Ingest Markdown Text';
      }
    });
  }

  document.getElementById('clearLogBtn')?.addEventListener('click', () => {
    const log = document.getElementById('ingestActivityLog');
    if (log) log.innerHTML = '<div class="console-entry info">Pipeline log cleared. Ready.</div>';
  });
}

function appendLog(message, type = 'info') {
  const logContainer = document.getElementById('ingestActivityLog');
  if (!logContainer) return;
  const entry = document.createElement('div');
  entry.className = `console-entry ${type}`;
  const time = new Date().toLocaleTimeString();
  entry.textContent = `[${time}] ${message}`;
  logContainer.appendChild(entry);
  logContainer.scrollTop = logContainer.scrollHeight;
}

// ==================== Research Dialogue & Chat ====================
function initResearchChat() {
  const form = document.getElementById('researchForm');
  const queryInput = document.getElementById('queryInput');
  const submitBtn = document.getElementById('submitQueryBtn');
  const messagesContainer = document.getElementById('chatMessages');

  if (!form || !queryInput) return;

  // Auto-resize query textarea as user types
  queryInput.addEventListener('input', () => {
    queryInput.style.height = 'auto';
    queryInput.style.height = Math.min(queryInput.scrollHeight, 180) + 'px';
  });

  // Enter to submit (Shift+Enter for newline)
  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event('submit'));
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    // Append user message
    appendUserMessage(query);
    queryInput.value = '';
    queryInput.style.height = 'auto';
    if (submitBtn) submitBtn.disabled = true;

    // Append loading assistant speech card
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
        loadingCard.querySelector('.speech-body').innerHTML = `
          <p style="color:var(--accent-rose); font-family:var(--font-display); font-weight:600;">
            Synthesis Error: ${escapeHtml(data.detail || 'Query failed')}
          </p>
        `;
      }
    } catch (err) {
      loadingCard.querySelector('.speech-body').innerHTML = `
        <p style="color:var(--accent-rose); font-family:var(--font-display); font-weight:600;">
          Connection Exception: ${escapeHtml(err.message)}
        </p>
      `;
    } finally {
      if (submitBtn) submitBtn.disabled = false;
      if (messagesContainer) messagesContainer.scrollTop = messagesContainer.scrollHeight;
      refreshTelemetry();
    }
  });
}

function appendUserMessage(text) {
  const container = document.getElementById('chatMessages');
  if (!container) return;

  const card = document.createElement('div');
  card.className = 'speech-card user-speech';
  card.innerHTML = `
    <div class="speech-header">
      <div class="speaker-title">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
        <span>Researcher Inquiry</span>
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
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
          <polyline points="2 17 12 22 22 17"></polyline>
          <polyline points="2 12 12 17 22 12"></polyline>
        </svg>
        <span>Research Knowledge Engine</span>
      </div>
      <span class="speech-time">Synthesizing...</span>
    </div>
    <div class="speech-body academic-narrative">
      <div style="display:flex; align-items:center; gap:12px; color:var(--text-secondary); font-family:var(--font-display); font-size:0.9rem; padding:8px 0;">
        <span class="live-indicator-dot live-indigo" style="animation:pulseGlow 1.2s infinite alternate;"></span>
        <span>Retrieving hybrid vectors & concept relationships... Groq LLM synthesis in progress</span>
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

  // Convert answer markdown to HTML using marked.js
  let rawAnswer = data.answer || '';
  
  // Transform [1], [2] to interactive inline citation badges
  rawAnswer = rawAnswer.replace(/\[(\d+)\]/g, (match, p1) => {
    return `<span class="inline-citation-badge" data-cite="${p1}">[${p1}]</span>`;
  });

  const parsedHtml = marked.parse(rawAnswer);

  let sourcesHtml = '';
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `
      <div class="sources-consulted-bar">
        <strong>Sources Consulted (${data.sources.length}):</strong>
        ${data.sources.map(s => `<span class="source-pill-token" title="${escapeHtml(s.source_path_or_url || '')}">${escapeHtml(s.title || s.id)}</span>`).join(' ')}
      </div>
    `;
  }

  const bodyEl = card.querySelector('.speech-body');
  if (bodyEl) {
    bodyEl.innerHTML = `
      <div class="academic-narrative">${parsedHtml}</div>
      ${sourcesHtml}
    `;

    // Attach citation chip click listeners
    bodyEl.querySelectorAll('.inline-citation-badge').forEach(badge => {
      badge.addEventListener('click', () => {
        const citeId = parseInt(badge.getAttribute('data-cite'));
        highlightCitation(citeId);
      });
    });
  }
}

function updateInspector(data) {
  currentCitations = data.citations || [];
  currentConcepts = data.related_concepts || [];
  currentProvenance = data.confidence_provenance || null;

  // 1. Render Citations Pane
  const citationsList = document.getElementById('citationsList');
  if (citationsList) {
    if (currentCitations.length === 0) {
      citationsList.innerHTML = `
        <div class="zero-data-state">
          <div class="zero-state-icon">📖</div>
          <div class="zero-state-heading">No Direct Citations</div>
          <div class="zero-state-desc">No verbatim citation quotes were linked to this synthesis turn.</div>
        </div>
      `;
    } else {
      citationsList.innerHTML = currentCitations.map(c => `
        <div class="citation-evidence-box" id="citationCard-${c.citation_id}">
          <div class="evidence-source-header">
            <span class="evidence-cite-badge">[${c.citation_id}]</span>
            <span class="evidence-title-text" title="${escapeHtml(c.source_title)}">${escapeHtml(c.source_title || 'Document')}</span>
          </div>
          <div class="verbatim-quote-box">"${escapeHtml(c.quote)}"</div>
          <div style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono); margin-top:8px;">
            ${c.page ? `Page ${c.page}` : 'Document chunk excerpt'}
          </div>
        </div>
      `).join('');
    }
  }

  // 2. Render Related Concepts Pane
  const conceptsList = document.getElementById('relatedConceptsList');
  if (conceptsList) {
    if (currentConcepts.length === 0) {
      conceptsList.innerHTML = `
        <div class="zero-data-state">
          <div class="zero-state-icon">🏷️</div>
          <div class="zero-state-heading">No Concepts Linked</div>
          <div class="zero-state-desc">No structured OKF concepts were matched to this inquiry.</div>
        </div>
      `;
    } else {
      conceptsList.innerHTML = currentConcepts.map(c => `
        <div class="concept-registry-card">
          <div class="concept-card-top">
            <span class="concept-label-name">${escapeHtml(c.name)}</span>
            <span class="concept-category-tag">${escapeHtml(c.category || 'Entity')}</span>
          </div>
          <div class="concept-definition-body">${escapeHtml(c.definition || 'No definition recorded.')}</div>
        </div>
      `).join('');
    }
  }

  // 3. Render Confidence & Provenance Pane
  const provContainer = document.getElementById('provenanceContainer');
  if (provContainer) {
    if (currentProvenance) {
      provContainer.innerHTML = `
        <div class="provenance-evidence-card">
          <div class="provenance-score-gauge">
            <div>
              <div style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">Grounding Confidence</div>
              <div class="score-number-display">${(currentProvenance.score * 100).toFixed(0)}%</div>
            </div>
            <span class="grounding-rating-pill">${escapeHtml(currentProvenance.rating)} Grounding</span>
          </div>
          <div class="provenance-narrative">${escapeHtml(currentProvenance.rationale)}</div>
          <div class="provenance-meta-row">
            <span>Sources Consulted</span>
            <span>${currentProvenance.sources_consulted}</span>
          </div>
          <div class="provenance-meta-row">
            <span>Concepts Linked</span>
            <span>${currentProvenance.concepts_linked}</span>
          </div>
        </div>
      `;
    } else {
      provContainer.innerHTML = `
        <div class="zero-data-state">
          <div class="zero-state-icon">🛡️</div>
          <div class="zero-state-heading">Provenance Ready</div>
          <div class="zero-state-desc">Submit a research question to compute grounding metrics.</div>
        </div>
      `;
    }
  }
}

function highlightCitation(citeId) {
  // Switch to Citations tab in inspector
  const citeTab = document.querySelector('.segment-btn[data-sub="sub-citations"], .sub-tab[data-sub="sub-citations"]');
  if (citeTab) citeTab.click();

  const el = document.getElementById(`citationCard-${citeId}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.style.borderColor = 'var(--accent-indigo)';
    el.style.boxShadow = '0 0 16px rgba(79, 70, 229, 0.35)';
    el.style.transform = 'translateY(-2px)';
    setTimeout(() => {
      el.style.borderColor = '';
      el.style.boxShadow = '';
      el.style.transform = '';
    }, 2500);
  }
}

// ==================== Cytoscape Knowledge Graph ====================
function initGraph() {
  const container = document.getElementById('cy');
  if (!container) return;

  cy = cytoscape({
    container: container,
    elements: [],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': '#e2e8f0',
          'label': 'data(label)',
          'color': '#0f172a',
          'font-family': 'Plus Jakarta Sans, sans-serif',
          'font-size': '11px',
          'font-weight': 600,
          'text-valign': 'bottom',
          'text-margin-y': 6,
          'width': 'mapData(mention_count, 1, 10, 28, 52)',
          'height': 'mapData(mention_count, 1, 10, 28, 52)',
          'border-width': 2.5,
          'border-color': '#64748b',
          'text-outline-color': '#ffffff',
          'text-outline-width': 2.5,
          'transition-property': 'background-color, line-color, target-arrow-color, border-color, shadow-blur',
          'transition-duration': '0.2s'
        }
      },
      {
        selector: 'node[category = "Architecture"]',
        style: { 'background-color': '#e0e7ff', 'border-color': '#4338ca', 'color': '#1e1b4b' }
      },
      {
        selector: 'node[category = "Mechanism"]',
        style: { 'background-color': '#f3e8ff', 'border-color': '#7e22ce', 'color': '#3b0764' }
      },
      {
        selector: 'node[category = "Tool"]',
        style: { 'background-color': '#dcfce7', 'border-color': '#059669', 'color': '#064e3b' }
      },
      {
        selector: 'node[category = "Entity"]',
        style: { 'background-color': '#fef3c7', 'border-color': '#d97706', 'color': '#78350f' }
      },
      {
        selector: 'node[category = "Metric"]',
        style: { 'background-color': '#ffe4e6', 'border-color': '#e11d48', 'color': '#881337' }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.8,
          'line-color': '#94a3b8',
          'target-arrow-color': '#64748b',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(label)',
          'font-family': 'JetBrains Mono, monospace',
          'font-size': '9px',
          'color': '#475569',
          'text-rotation': 'autorotate',
          'text-outline-color': '#ffffff',
          'text-outline-width': 1.5
        }
      },
      {
        selector: ':selected',
        style: {
          'border-width': 4,
          'border-color': '#4f46e5',
          'shadow-blur': 16,
          'shadow-color': 'rgba(79, 70, 229, 0.4)',
          'shadow-opacity': 0.8
        }
      }
    ],
    layout: { name: 'cose', animate: false }
  });

  cy.on('tap', 'node', (evt) => {
    const node = evt.target;
    const data = node.data();
    showNodeDetails(data);
  });

  document.getElementById('resetGraphBtn')?.addEventListener('click', () => {
    cy.layout({ name: 'cose', animate: true, padding: 40 }).run();
  });
  document.getElementById('refreshGraphBtn')?.addEventListener('click', loadGraphData);

  loadGraphData();
}

async function loadGraphData() {
  if (!cy) return;
  try {
    const res = await fetch('/api/graph');
    if (res.ok) {
      const data = await res.json();
      const elements = [];

      (data.nodes || []).forEach(n => {
        elements.push({
          group: 'nodes',
          data: {
            id: n.id,
            label: n.label,
            category: n.category,
            definition: n.definition,
            mention_count: n.mention_count || 1
          }
        });
      });

      (data.edges || []).forEach(e => {
        elements.push({
          group: 'edges',
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
            description: e.description,
            evidence: e.evidence
          }
        });
      });

      cy.elements().remove();
      cy.add(elements);
      cy.layout({ name: 'cose', animate: true, padding: 40 }).run();
    }
  } catch (err) {
    console.warn('Failed to load graph data', err);
  }
}

function showNodeDetails(nodeData) {
  const titleEl = document.getElementById('selectedNodeName');
  const detailsEl = document.getElementById('selectedNodeDetails');
  if (titleEl) titleEl.textContent = nodeData.label || 'Concept';

  if (detailsEl) {
    detailsEl.innerHTML = `
      <div style="margin-bottom:14px; display:flex; align-items:center; gap:8px;">
        <span class="concept-category-tag" style="font-size:0.8rem; padding:3px 10px;">${escapeHtml(nodeData.category || 'Entity')}</span>
        <span style="font-size:0.8rem; color:var(--text-muted); font-family:var(--font-mono);">Mentions: ${nodeData.mention_count || 1}</span>
      </div>
      <div style="font-size:0.88rem; color:var(--text-secondary); line-height:1.6; margin-bottom:18px;">
        <strong style="color:var(--text-primary); display:block; margin-bottom:4px;">Definition:</strong>
        <p>${escapeHtml(nodeData.definition || 'No definition recorded.')}</p>
      </div>
      <button class="btn-primary-action" style="font-size:0.84rem; padding:10px;" onclick="inspectOkfFor('${escapeHtml(nodeData.id)}')">View OKF YAML Card</button>
    `;
  }
}

window.inspectOkfFor = (conceptId) => {
  const okfTab = document.querySelector('.workstation-tab[data-tab="tab-okf"], .nav-tab[data-tab="tab-okf"]');
  if (okfTab) okfTab.click();
  loadConceptOkf(conceptId);
};

// ==================== OKF Layer Explorer ====================
async function initOkfExplorer() {
  document.getElementById('copyOkfBtn')?.addEventListener('click', () => {
    const textEl = document.getElementById('okfMarkdownContent');
    if (textEl) {
      navigator.clipboard.writeText(textEl.innerText);
      alert('OKF Markdown + YAML copied to clipboard!');
    }
  });

  const filterInput = document.getElementById('filterConceptsInput');
  filterInput?.addEventListener('input', (e) => {
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
    if (res.ok) {
      const concepts = await res.json();
      if (concepts.length === 0) {
        listEl.innerHTML = `
          <div class="zero-data-state">
            <div class="zero-state-icon">📂</div>
            <div class="zero-state-heading">No Concepts Loaded</div>
            <div class="zero-state-desc">Ingest a research document to extract and inspect typed OKF objects.</div>
          </div>
        `;
        return;
      }

      listEl.innerHTML = concepts.map(c => `
        <div class="okf-menu-item" data-id="${escapeHtml(c._id || c.name)}">
          <div class="okf-item-head">${escapeHtml(c.name)}</div>
          <div class="okf-item-caption">
            <span>${escapeHtml(c.category || 'Entity')}</span> • <span>Mentions: ${c.mention_count || 1}</span>
          </div>
        </div>
      `).join('');

      listEl.querySelectorAll('.okf-menu-item').forEach(item => {
        item.addEventListener('click', () => {
          listEl.querySelectorAll('.okf-menu-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
          loadConceptOkf(item.getAttribute('data-id'));
        });
      });

      // Load first concept by default if none active
      if (concepts.length > 0) {
        const firstItem = listEl.querySelector('.okf-menu-item');
        if (firstItem) {
          firstItem.classList.add('active');
          loadConceptOkf(concepts[0]._id || concepts[0].name);
        }
      }
    }
  } catch (err) {
    listEl.innerHTML = `
      <div class="zero-data-state">
        <div class="zero-state-icon">⚠️</div>
        <div class="zero-state-heading">Load Failed</div>
        <div class="zero-state-desc">${escapeHtml(err.message)}</div>
      </div>
    `;
  }
}

async function loadConceptOkf(conceptId) {
  try {
    const res = await fetch(`/api/okf/concept/${encodeURIComponent(conceptId)}`);
    if (res.ok) {
      const data = await res.json();
      const titleEl = document.getElementById('okfPreviewTitle');
      const contentEl = document.getElementById('okfMarkdownContent');
      if (titleEl) titleEl.textContent = `OKF Object: ${data.name}`;
      if (contentEl) contentEl.textContent = data.okf_markdown;
    }
  } catch (err) {
    console.warn('Failed to load OKF for concept', err);
  }
}

// ==================== Dual Storage Inspector ====================
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
    if (!confirm('Are you sure you want to completely purge all ingested documents, concepts, relationships, and vector chunks?')) {
      return;
    }
    try {
      const res = await fetch('/api/storage/clear', { method: 'POST' });
      if (res.ok) {
        alert('All ingested data, concepts, and vector embeddings have been purged.');
        refreshTelemetry();
        loadGraphData();
        loadOkfConcepts();
        const activeCol = document.querySelector('.store-tab.active')?.getAttribute('data-col') || 'col-docs';
        loadStorageData(activeCol);
      }
    } catch (err) {
      alert(`Error clearing storage: ${err.message}`);
    }
  });
}

async function loadStorageData(col) {
  const thead = document.getElementById('tableHeadRow');
  const tbody = document.getElementById('tableBody');
  if (!thead || !tbody) return;

  if (col === 'col-docs') {
    thead.innerHTML = '<th>Title</th><th>Type</th><th>Chunks</th><th>Concepts</th><th>Relationships</th><th>Created At</th>';
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:32px; color:var(--text-muted);">Querying MongoDB documents collection...</td></tr>';
    try {
      const res = await fetch('/api/documents');
      const docs = await res.json();
      if (docs.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6">
              <div class="zero-data-state">
                <div class="zero-state-icon">📄</div>
                <div class="zero-state-heading">No Documents Ingested</div>
                <div class="zero-state-desc">Upload a PDF, URL, or Markdown file to populate the research registry.</div>
              </div>
            </td>
          </tr>
        `;
        return;
      }
      tbody.innerHTML = docs.map(d => `
        <tr>
          <td><strong>${escapeHtml(d.title || d._id)}</strong></td>
          <td><span class="concept-category-tag">${escapeHtml(d.source_type || 'doc')}</span></td>
          <td>${d.total_chunks || 0}</td>
          <td>${d.total_concepts || 0}</td>
          <td>${d.total_relationships || 0}</td>
          <td style="font-size:0.78rem; font-family:var(--font-mono); color:var(--text-muted);">${escapeHtml(d.created_at || '')}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:var(--accent-rose); text-align:center; padding:24px;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
  } else if (col === 'col-concepts') {
    thead.innerHTML = '<th>Concept Name</th><th>Category</th><th>Definition</th><th>Mentions</th>';
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:32px; color:var(--text-muted);">Querying MongoDB concepts collection...</td></tr>';
    try {
      const res = await fetch('/api/concepts');
      const concepts = await res.json();
      if (concepts.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="4">
              <div class="zero-data-state">
                <div class="zero-state-icon">🏷️</div>
                <div class="zero-state-heading">No Concepts Stored</div>
                <div class="zero-state-desc">Extracted OKF concepts will be listed here.</div>
              </div>
            </td>
          </tr>
        `;
        return;
      }
      tbody.innerHTML = concepts.map(c => `
        <tr>
          <td><strong>${escapeHtml(c.name)}</strong></td>
          <td><span class="concept-category-tag">${escapeHtml(c.category || 'Entity')}</span></td>
          <td style="font-size:0.84rem; color:var(--text-secondary); max-width:440px;">${escapeHtml(c.definition || '')}</td>
          <td style="font-family:var(--font-mono); font-weight:600;">${c.mention_count || 1}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:var(--accent-rose); text-align:center; padding:24px;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
  } else if (col === 'col-rels') {
    thead.innerHTML = '<th>Source Concept</th><th>Relation Type</th><th>Target Concept</th><th>Description / Evidence</th>';
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:32px; color:var(--text-muted);">Querying MongoDB relationships collection...</td></tr>';
    try {
      const res = await fetch('/api/relationships');
      const rels = await res.json();
      if (rels.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="4">
              <div class="zero-data-state">
                <div class="zero-state-icon">🕸️</div>
                <div class="zero-state-heading">No Relationships Stored</div>
                <div class="zero-state-desc">Graph edges extracted between concepts will be cataloged here.</div>
              </div>
            </td>
          </tr>
        `;
        return;
      }
      tbody.innerHTML = rels.map(r => `
        <tr>
          <td><strong>${escapeHtml(r.source)}</strong></td>
          <td><span class="concept-category-tag" style="background:#f3e8ff; color:#7e22ce;">${escapeHtml(r.relation_type)}</span></td>
          <td><strong>${escapeHtml(r.target)}</strong></td>
          <td style="font-size:0.84rem; color:var(--text-secondary);">${escapeHtml(r.description || r.evidence || '')}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:var(--accent-rose); text-align:center; padding:24px;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
  } else if (col === 'col-sources') {
    thead.innerHTML = '<th>Title</th><th>Modality</th><th>URI / File Path</th><th>Total Chunks</th>';
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:32px; color:var(--text-muted);">Querying MongoDB sources collection...</td></tr>';
    try {
      const res = await fetch('/api/sources');
      const sources = await res.json();
      if (sources.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="4">
              <div class="zero-data-state">
                <div class="zero-state-icon">🗂️</div>
                <div class="zero-state-heading">No Sources Tracked</div>
                <div class="zero-state-desc">Original source files and URLs will be indexed here.</div>
              </div>
            </td>
          </tr>
        `;
        return;
      }
      tbody.innerHTML = sources.map(s => `
        <tr>
          <td><strong>${escapeHtml(s.title || s.id)}</strong></td>
          <td><span class="concept-category-tag">${escapeHtml(s.source_type)}</span></td>
          <td style="font-size:0.8rem; font-family:var(--font-mono);">${escapeHtml(s.source_path_or_url || '')}</td>
          <td style="font-family:var(--font-mono); font-weight:600;">${s.total_chunks || 0}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:var(--accent-rose); text-align:center; padding:24px;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
  }
}

// ==================== Settings Modal ====================
function initSettingsModal() {
  const modal = document.getElementById('settingsModal');
  const openBtn = document.getElementById('openSettingsBtn');
  const closeBtn = document.getElementById('closeSettingsBtn');
  const cancelBtn = document.getElementById('cancelSettingsBtn');
  const form = document.getElementById('settingsForm');

  if (!modal) return;

  const openModal = async () => {
    modal.classList.add('open');
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        const modelSel = document.getElementById('groqModelSelect');
        const uriInput = document.getElementById('mongoUriInput');
        const hint = document.getElementById('apiKeyStatusHint');

        if (modelSel && data.groq_model) modelSel.value = data.groq_model;
        if (uriInput) uriInput.value = (data.mongodb_uri && data.mongodb_uri.startsWith('mongodb')) ? data.mongodb_uri : '';
        if (hint) {
          hint.textContent = data.groq_api_key_set
            ? `Active Key: ${data.groq_api_key_preview}`
            : 'Status: Using environment default key';
        }
      }
    } catch (err) {
      console.warn('Failed to load settings', err);
    }
  };

  const closeModal = () => modal.classList.remove('open');

  openBtn?.addEventListener('click', openModal);
  closeBtn?.addEventListener('click', closeModal);
  cancelBtn?.addEventListener('click', closeModal);

  // Close modal when clicking scrim outside box
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const groqKey = document.getElementById('groqApiKeyInput')?.value.trim();
    const model = document.getElementById('groqModelSelect')?.value;
    const mongoUri = document.getElementById('mongoUriInput')?.value.trim();

    const payload = {
      groq_model: model,
      mongodb_uri: mongoUri || ''
    };
    if (groqKey) {
      payload.groq_api_key = groqKey;
    }

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        alert('Settings updated successfully!');
        closeModal();
        refreshTelemetry();
      } else {
        const errData = await res.json();
        alert(`Error saving settings: ${errData.detail || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error saving settings: ${err.message}`);
    }
  });
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
