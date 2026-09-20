// Research Knowledge Engine Client Application

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
  const tabs = document.querySelectorAll('.nav-tab');
  const panels = document.querySelectorAll('.tab-panel');

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
          loadStorageData('col-docs');
        } else if (targetId === 'tab-okf') {
          loadOkfConcepts();
        }
      }
    });
  });

  // Inspector sub-tabs
  const subTabs = document.querySelectorAll('.sub-tab');
  const subPanels = document.querySelectorAll('.sub-panel');
  subTabs.forEach(st => {
    st.addEventListener('click', () => {
      const subId = st.getAttribute('data-sub');
      subTabs.forEach(s => s.classList.remove('active'));
      subPanels.forEach(p => p.classList.remove('active'));
      st.classList.add('active');
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
      document.getElementById('mongoStatusText').textContent = isLive ? 'Live MongoDB' : 'Embedded Mock';
      document.getElementById('vectorCountText').textContent = vec.total_chunks || 0;
      document.getElementById('conceptCountText').textContent = mongo.counts?.concepts || 0;

      // Update storage tab counts
      if (mongo.counts) {
        document.getElementById('statDocs').textContent = mongo.counts.documents || 0;
        document.getElementById('statConcepts').textContent = mongo.counts.concepts || 0;
        document.getElementById('statRels').textContent = mongo.counts.relationships || 0;
        document.getElementById('statSources').textContent = mongo.counts.sources || 0;
        document.getElementById('statChunks').textContent = vec.total_chunks || 0;
      }

      if (data.groq_model) {
        document.getElementById('activeModelBadge').textContent = `Groq: ${data.groq_model}`;
      }
    }
  } catch (err) {
    console.warn('Telemetry update failed', err);
  }
}

// ==================== Ingestion Hub ====================
function initIngestion() {
  const pdfDropZone = document.getElementById('pdfDropZone');
  const pdfFileInput = document.getElementById('pdfFileInput');
  const uploadPdfBtn = document.getElementById('uploadPdfBtn');
  const pdfSelectedName = document.getElementById('pdfSelectedName');
  let selectedPdfFile = null;

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

  uploadPdfBtn.addEventListener('click', async () => {
    if (!selectedPdfFile) return;
    uploadPdfBtn.disabled = true;
    uploadPdfBtn.textContent = 'Ingesting PDF...';
    appendLog(`Ingesting PDF: ${selectedPdfFile.name} using PyMuPDF...`, 'info');

    const formData = new FormData();
    formData.append('file', selectedPdfFile);

    try {
      const res = await fetch('/api/ingest/pdf', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        appendLog(`Successfully ingested PDF: "${data.title}" -> ${data.chunks_count} chunks, ${data.concepts_count} OKF concepts, ${data.relationships_count} relationships. OKF exported to: ${data.okf_export_path}`, 'success');
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

  // URL Ingest
  const urlForm = document.getElementById('urlIngestForm');
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

  // Text/Markdown Ingest
  const textForm = document.getElementById('textIngestForm');
  textForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const titleInput = document.getElementById('textTitleInput');
    const contentInput = document.getElementById('textContentInput');
    const saveBtn = document.getElementById('saveTextBtn');
    const title = titleInput.value.trim();
    const content = contentInput.value.trim();
    if (!content) return;

    saveBtn.disabled = true;
    saveBtn.textContent = 'Processing Markdown...';
    appendLog(`Ingesting Markdown Note: "${title}"...`, 'info');

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

  document.getElementById('clearLogBtn')?.addEventListener('click', () => {
    document.getElementById('ingestActivityLog').innerHTML = '';
  });
}

function appendLog(message, type = 'info') {
  const logContainer = document.getElementById('ingestActivityLog');
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
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

  // Sample query buttons
  document.querySelectorAll('.btn-sample-query').forEach(btn => {
    btn.addEventListener('click', () => {
      queryInput.value = btn.textContent.trim();
      form.dispatchEvent(new Event('submit'));
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    // Append user message
    appendUserMessage(query);
    queryInput.value = '';
    submitBtn.disabled = true;

    // Append loading assistant message
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
        loadingCard.querySelector('.message-content').innerHTML = `<p class="error-msg">Error: ${data.detail || 'Query failed'}</p>`;
      }
    } catch (err) {
      loadingCard.querySelector('.message-content').innerHTML = `<p class="error-msg">Exception: ${err.message}</p>`;
    } finally {
      submitBtn.disabled = false;
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      refreshTelemetry();
    }
  });
}

function appendUserMessage(text) {
  const container = document.getElementById('chatMessages');
  const card = document.createElement('div');
  card.className = 'message-card user';
  card.innerHTML = `
    <div class="message-header">
      <div class="author-badge">Researcher</div>
      <div class="timestamp">${new Date().toLocaleTimeString()}</div>
    </div>
    <div class="message-content">
      <p>${escapeHtml(text)}</p>
    </div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

function appendAssistantLoading() {
  const container = document.getElementById('chatMessages');
  const card = document.createElement('div');
  card.className = 'message-card assistant';
  card.innerHTML = `
    <div class="message-header">
      <div class="author-badge">Research Knowledge Engine</div>
      <div class="timestamp">Synthesizing...</div>
    </div>
    <div class="message-content">
      <div class="loading-indicator">
        <span>Retrieving hybrid vectors & concept graph... Groq RAG synthesis in progress</span>
      </div>
    </div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
  return card;
}

function updateAssistantCard(card, data) {
  card.querySelector('.timestamp').textContent = new Date().toLocaleTimeString();

  // Convert answer markdown to HTML using marked
  let rawAnswer = data.answer || '';
  // Transform [1], [2] to interactive citation chips
  rawAnswer = rawAnswer.replace(/\[(\d+)\]/g, (match, p1) => {
    return `<span class="cite-tag" data-cite="${p1}">[${p1}]</span>`;
  });

  const parsedHtml = marked.parse(rawAnswer);

  let sourcesHtml = '';
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `
      <div class="message-sources-summary">
        <strong>Sources Consulted (${data.sources.length}):</strong>
        ${data.sources.map(s => `<span class="pill-hint">${escapeHtml(s.title || s.id)}</span>`).join(' ')}
      </div>
    `;
  }

  card.querySelector('.message-content').innerHTML = `
    <div class="markdown-body">${parsedHtml}</div>
    ${sourcesHtml}
  `;

  // Attach citation chip click listeners
  card.querySelectorAll('.cite-tag').forEach(tag => {
    tag.addEventListener('click', () => {
      const citeId = parseInt(tag.getAttribute('data-cite'));
      highlightCitation(citeId);
    });
  });
}

function updateInspector(data) {
  currentCitations = data.citations || [];
  currentConcepts = data.related_concepts || [];
  currentProvenance = data.confidence_provenance || null;

  // Render Citations
  const citationsList = document.getElementById('citationsList');
  if (currentCitations.length === 0) {
    citationsList.innerHTML = '<p class="empty-state">No direct citations recorded for this answer.</p>';
  } else {
    citationsList.innerHTML = currentCitations.map(c => `
      <div class="citation-card" id="citationCard-${c.citation_id}">
        <div class="citation-header">
          <span class="cite-num">[${c.citation_id}]</span>
          <span class="cite-source-title" title="${escapeHtml(c.source_title)}">${escapeHtml(c.source_title || 'Document')}</span>
        </div>
        <div class="citation-quote">"${escapeHtml(c.quote)}"</div>
        <div class="prov-meta-item" style="margin-top:6px;">
          <span>Page / Section:</span>
          <span>${c.page ? `Page ${c.page}` : 'Document chunk'}</span>
        </div>
      </div>
    `).join('');
  }

  // Render Related Concepts
  const conceptsList = document.getElementById('relatedConceptsList');
  if (currentConcepts.length === 0) {
    conceptsList.innerHTML = '<p class="empty-state">No concepts retrieved for this query.</p>';
  } else {
    conceptsList.innerHTML = currentConcepts.map(c => `
      <div class="concept-chip">
        <div class="concept-chip-header">
          <span class="concept-name">${escapeHtml(c.name)}</span>
          <span class="concept-cat">${escapeHtml(c.category)}</span>
        </div>
        <div class="concept-def">${escapeHtml(c.definition)}</div>
      </div>
    `).join('');
  }

  // Render Provenance
  const provContainer = document.getElementById('provenanceContainer');
  if (currentProvenance) {
    provContainer.innerHTML = `
      <div class="provenance-card">
        <div class="prov-score-row">
          <div>
            <div class="pill-label">Confidence Score</div>
            <div class="prov-score-val">${(currentProvenance.score * 100).toFixed(0)}%</div>
          </div>
          <div class="prov-rating-badge">${escapeHtml(currentProvenance.rating)} Grounding</div>
        </div>
        <div class="prov-rationale">${escapeHtml(currentProvenance.rationale)}</div>
        <div class="prov-meta-item">
          <span>Sources Consulted:</span>
          <span>${currentProvenance.sources_consulted}</span>
        </div>
        <div class="prov-meta-item">
          <span>Concepts Linked:</span>
          <span>${currentProvenance.concepts_linked}</span>
        </div>
      </div>
    `;
  }
}

function highlightCitation(citeId) {
  // Switch to Citations tab in inspector
  document.querySelector('.sub-tab[data-sub="sub-citations"]')?.click();
  const el = document.getElementById(`citationCard-${citeId}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.style.borderColor = 'var(--accent-cyan)';
    el.style.boxShadow = '0 0 16px rgba(0, 242, 254, 0.4)';
    setTimeout(() => {
      el.style.borderColor = '';
      el.style.boxShadow = '';
    }, 2000);
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
          'background-color': '#38bdf8',
          'label': 'data(label)',
          'color': '#f8fafc',
          'font-family': 'Outfit, sans-serif',
          'font-size': '11px',
          'text-valign': 'bottom',
          'text-margin-y': 6,
          'width': 'mapData(mention_count, 1, 10, 26, 50)',
          'height': 'mapData(mention_count, 1, 10, 26, 50)',
          'border-width': 2,
          'border-color': 'rgba(255, 255, 255, 0.3)',
          'transition-property': 'background-color, line-color, target-arrow-color',
          'transition-duration': '0.2s'
        }
      },
      {
        selector: 'node[category = "Architecture"]',
        style: { 'background-color': '#38bdf8', 'border-color': '#0284c7' }
      },
      {
        selector: 'node[category = "Mechanism"]',
        style: { 'background-color': '#a855f7', 'border-color': '#7e22ce' }
      },
      {
        selector: 'node[category = "Tool"]',
        style: { 'background-color': '#10b981', 'border-color': '#047857' }
      },
      {
        selector: 'node[category = "Entity"]',
        style: { 'background-color': '#f59e0b', 'border-color': '#b45309' }
      },
      {
        selector: 'node[category = "Metric"]',
        style: { 'background-color': '#f43f5e', 'border-color': '#be123c' }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': 'rgba(255, 255, 255, 0.18)',
          'target-arrow-color': 'rgba(255, 255, 255, 0.28)',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'label': 'data(label)',
          'font-family': 'JetBrains Mono, monospace',
          'font-size': '9px',
          'color': '#94a3b8',
          'text-rotation': 'autorotate'
        }
      },
      {
        selector: ':selected',
        style: {
          'border-width': 4,
          'border-color': '#00f2fe',
          'shadow-blur': 15,
          'shadow-color': '#00f2fe',
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
    cy.layout({ name: 'cose', animate: true }).run();
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
      cy.layout({ name: 'cose', animate: true, padding: 30 }).run();
    }
  } catch (err) {
    console.warn('Failed to load graph data', err);
  }
}

function showNodeDetails(nodeData) {
  const titleEl = document.getElementById('selectedNodeName');
  const detailsEl = document.getElementById('selectedNodeDetails');
  titleEl.textContent = nodeData.label || 'Concept';

  detailsEl.innerHTML = `
    <div style="margin-bottom:12px;">
      <span class="panel-badge">${escapeHtml(nodeData.category || 'Entity')}</span>
      <span style="font-size:0.78rem; color:var(--text-muted); margin-left:8px;">Mentions: ${nodeData.mention_count || 1}</span>
    </div>
    <div style="font-size:0.85rem; color:var(--text-primary); line-height:1.5; margin-bottom:14px;">
      <strong>Definition:</strong>
      <p style="margin-top:4px;">${escapeHtml(nodeData.definition || 'No definition recorded.')}</p>
    </div>
    <button class="btn-primary" style="width:100%; font-size:0.82rem;" onclick="inspectOkfFor('${escapeHtml(nodeData.id)}')">View OKF YAML Card</button>
  `;
}

window.inspectOkfFor = (conceptId) => {
  document.querySelector('.nav-tab[data-tab="tab-okf"]')?.click();
  loadConceptOkf(conceptId);
};

// ==================== OKF Layer Explorer ====================
async function initOkfExplorer() {
  document.getElementById('copyOkfBtn')?.addEventListener('click', () => {
    const text = document.getElementById('okfMarkdownContent').innerText;
    navigator.clipboard.writeText(text);
    alert('OKF Markdown + YAML copied to clipboard!');
  });

  const filterInput = document.getElementById('filterConceptsInput');
  filterInput?.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    document.querySelectorAll('.okf-item').forEach(item => {
      const name = item.querySelector('.okf-item-title').textContent.toLowerCase();
      item.style.display = name.includes(term) ? 'block' : 'none';
    });
  });
}

async function loadOkfConcepts() {
  const listEl = document.getElementById('okfConceptsList');
  try {
    const res = await fetch('/api/concepts');
    if (res.ok) {
      const concepts = await res.json();
      if (concepts.length === 0) {
        listEl.innerHTML = '<div class="empty-state">No OKF concepts extracted yet. Ingest documents first.</div>';
        return;
      }

      listEl.innerHTML = concepts.map(c => `
        <div class="okf-item" data-id="${c._id || c.name}">
          <div class="okf-item-title">${escapeHtml(c.name)}</div>
          <div class="okf-item-meta">
            <span>${escapeHtml(c.category || 'Entity')}</span>
            <span>•</span>
            <span>Mentions: ${c.mention_count || 1}</span>
          </div>
        </div>
      `).join('');

      listEl.querySelectorAll('.okf-item').forEach(item => {
        item.addEventListener('click', () => {
          listEl.querySelectorAll('.okf-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
          loadConceptOkf(item.getAttribute('data-id'));
        });
      });

      // Load first concept by default
      if (concepts.length > 0) {
        loadConceptOkf(concepts[0]._id || concepts[0].name);
      }
    }
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Error: ${err.message}</div>`;
  }
}

async function loadConceptOkf(conceptId) {
  try {
    const res = await fetch(`/api/okf/concept/${encodeURIComponent(conceptId)}`);
    if (res.ok) {
      const data = await res.json();
      document.getElementById('okfPreviewTitle').textContent = `OKF Object: ${data.name}`;
      document.getElementById('okfMarkdownContent').textContent = data.okf_markdown;
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
}

async function loadStorageData(col) {
  const thead = document.getElementById('tableHeadRow');
  const tbody = document.getElementById('tableBody');

  if (col === 'col-docs') {
    thead.innerHTML = '<th>Title</th><th>Type</th><th>Chunks</th><th>Concepts</th><th>Relationships</th><th>Created</th>';
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Loading documents...</td></tr>';
    try {
      const res = await fetch('/api/documents');
      const docs = await res.json();
      if (docs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No documents stored in MongoDB yet.</td></tr>';
        return;
      }
      tbody.innerHTML = docs.map(d => `
        <tr>
          <td><strong>${escapeHtml(d.title || d._id)}</strong></td>
          <td><span class="panel-badge">${escapeHtml(d.source_type || 'doc')}</span></td>
          <td>${d.total_chunks || 0}</td>
          <td>${d.total_concepts || 0}</td>
          <td>${d.total_relationships || 0}</td>
          <td style="font-size:0.75rem; color:var(--text-muted);">${d.created_at || ''}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Error: ${e.message}</td></tr>`;
    }
  } else if (col === 'col-concepts') {
    thead.innerHTML = '<th>Concept Name</th><th>Category</th><th>Definition</th><th>Mentions</th>';
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Loading concepts...</td></tr>';
    try {
      const res = await fetch('/api/concepts');
      const concepts = await res.json();
      if (concepts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No concepts found in MongoDB concepts collection.</td></tr>';
        return;
      }
      tbody.innerHTML = concepts.map(c => `
        <tr>
          <td><strong>${escapeHtml(c.name)}</strong></td>
          <td><span class="panel-badge">${escapeHtml(c.category || 'Entity')}</span></td>
          <td style="font-size:0.8rem; color:var(--text-secondary); max-width:400px;">${escapeHtml(c.definition || '')}</td>
          <td>${c.mention_count || 1}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Error: ${e.message}</td></tr>`;
    }
  } else if (col === 'col-rels') {
    thead.innerHTML = '<th>Source Concept</th><th>Relation</th><th>Target Concept</th><th>Description</th>';
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Loading relationships...</td></tr>';
    try {
      const res = await fetch('/api/relationships');
      const rels = await res.json();
      if (rels.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No relationship edges stored in MongoDB yet.</td></tr>';
        return;
      }
      tbody.innerHTML = rels.map(r => `
        <tr>
          <td><strong>${escapeHtml(r.source)}</strong></td>
          <td><span class="panel-badge" style="color:var(--accent-purple);">${escapeHtml(r.relation_type)}</span></td>
          <td><strong>${escapeHtml(r.target)}</strong></td>
          <td style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(r.description || '')}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Error: ${e.message}</td></tr>`;
    }
  } else if (col === 'col-sources') {
    thead.innerHTML = '<th>Title</th><th>Type</th><th>Location / URL</th><th>Chunks</th>';
    tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Loading sources...</td></tr>';
    try {
      const res = await fetch('/api/sources');
      const sources = await res.json();
      if (sources.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No sources in MongoDB sources collection.</td></tr>';
        return;
      }
      tbody.innerHTML = sources.map(s => `
        <tr>
          <td><strong>${escapeHtml(s.title || s.id)}</strong></td>
          <td><span class="panel-badge">${escapeHtml(s.source_type)}</span></td>
          <td style="font-size:0.78rem; font-family:var(--font-mono);">${escapeHtml(s.source_path_or_url || '')}</td>
          <td>${s.total_chunks || 0}</td>
        </tr>
      `).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Error: ${e.message}</td></tr>`;
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

  const openModal = async () => {
    modal.classList.add('open');
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        document.getElementById('groqModelSelect').value = data.groq_model || 'llama-3.3-70b-versatile';
        document.getElementById('mongoUriInput').value = data.mongodb_uri.startsWith('mongodb') ? data.mongodb_uri : '';
        document.getElementById('apiKeyStatusHint').textContent = data.groq_api_key_set
          ? `Key active: ${data.groq_api_key_preview}`
          : 'Status: No Groq key configured (Using intelligent heuristic mode)';
      }
    } catch (err) {}
  };

  const closeModal = () => modal.classList.remove('open');

  openBtn.addEventListener('click', openModal);
  closeBtn.addEventListener('click', closeModal);
  cancelBtn.addEventListener('click', closeModal);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const groqKey = document.getElementById('groqApiKeyInput').value.trim();
    const model = document.getElementById('groqModelSelect').value;
    const mongoUri = document.getElementById('mongoUriInput').value.trim();

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
