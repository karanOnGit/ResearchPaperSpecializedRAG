# Research Knowledge Engine (RAG OKF LangChain Application)

An end-to-end Object Knowledge Format (OKF) retrieval-augmented generation (RAG) system built with LangChain, PyMuPDF, Groq LLM, MongoDB, and ChromaDB.

```
                         RESEARCH KNOWLEDGE ENGINE
┌─────────────────────────────────────────────────────────────────┐
│                         INPUT SOURCES                            │
│                                                                 │
│       PDF              URL              Markdown / TXT           │
└─────────┬───────────────┬───────────────────┬───────────────────┘
          │               │                   │
          └───────────────┴───────────────────┘
                          │
                          ▼
                ┌───────────────────┐
                │ Document Ingestion│
                │                  │
                │ PyMuPDF          │
                │ Web Loader       │
                │ Markdown Loader  │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │ Text Cleaning &   │
                │ Chunking          │
                └─────────┬─────────┘
                          │
                          ▼
                ┌───────────────────┐
                │ Groq LLM          │
                │ Knowledge         │
                │ Extraction        │
                └─────────┬─────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │        OKF Layer        │
              │                         │
              │ Typed concepts          │
              │ Relationships            │
              │ Sources                  │
              │ Provenance               │
              │ Markdown + YAML          │
              └───────────┬─────────────┘
                          │
                 ┌────────┴─────────┐
                 │                  │
                 ▼                  ▼
        ┌─────────────────┐  ┌──────────────────┐
        │    MongoDB      │  │ Vector Index     │
        │                 │  │                  │
        │ Documents       │  │ Embeddings       │
        │ Concepts        │  │ Chunks            │
        │ Sources         │  │ Metadata          │
        │ Relationships   │  │                  │
        │ Chat history    │  │                  │
        └────────┬────────┘  └────────┬─────────┘
                 │                    │
                 └──────────┬─────────┘
                            ▼
                   ┌─────────────────┐
                   │    LangChain    │
                   │ Hybrid Retriever│
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │   Groq LLM      │
                   │      RAG        │
                   └────────┬────────┘
                            │
                            ▼
                ┌───────────────────────┐
                │ Research Answer       │
                │                       │
                │ Answer                │
                │ Sources               │
                │ Citations             │
                │ Related concepts      │
                │ Confidence/provenance │
                └───────────────────────┘
```

---

## Features

- **Document Ingestion Hub**:
  - **PDF**: PyMuPDF (`fitz`) page-level text and layout extraction.
  - **URL**: Trafilatura & BeautifulSoup4 for clean web article extraction.
  - **Markdown / TXT**: Heading structure and YAML frontmatter preservation.
- **Text Cleaning & Semantic Chunking**: Normalized tokenization with recursive boundary splitting.
- **Groq LLM Knowledge Extraction**: Extracts typed concepts (`Architecture`, `Mechanism`, `Tool`, `Entity`, `Metric`), directed relationships, and provenance metadata.
- **OKF Layer (Object Knowledge Format)**: Bidirectional serialization to standard Markdown + YAML frontmatter.
- **Dual Storage Persistence**:
  - **MongoDB**: Stores collections for `documents`, `concepts`, `relationships`, `sources`, and `chat_history` (supports Atlas, local, or embedded persistent fallback).
  - **ChromaDB Vector Store**: Dense vector chunk embeddings using `sentence-transformers/all-MiniLM-L6-v2`.
- **LangChain Hybrid Retriever**: Fuses dense vector similarity with 1-hop MongoDB concept graph traversal via Reciprocal Rank Fusion (RRF).
- **Groq LLM RAG Synthesis**: Generates grounded research answers with inline citations, verbatim quotes, and provenance evaluation.
- **Modern Cyber-Scientific UI**: Interactive Cytoscape knowledge graph canvas, research dialogue, and dual storage inspector.

---

## Quickstart

### 1. Clone and Install Dependencies

```bash
git clone https://github.com/karanOnGit/ResearchPaperSpecializedRAG.git
cd ResearchPaperSpecializedRAG

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and add your **Groq API Key**:
```bash
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b
MONGODB_URI=  # Optional: Leave blank to use embedded persistent store
```

### 3. Run the Application

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

Open your browser at **`http://localhost:8000`**.

---

## Testing

Run the automated test suite:

```bash
PYTHONPATH=. python3 tests/test_okf.py
PYTHONPATH=. python3 tests/test_ingestion.py
PYTHONPATH=. python3 tests/test_pipeline.py
```
