import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import config
from app.engine import ResearchKnowledgeEngine
from app.okf.serializer import OKFSerializer
from app.okf.models import OKFConcept

app = FastAPI(
    title="Research Knowledge Engine - RAG OKF LangChain Application",
    description="Full-stack object retrieval RAG engine featuring PyMuPDF/Web/Markdown ingestion, Groq LLM extraction, OKF layer, MongoDB + Vector Index dual storage, LangChain Hybrid Retriever, and Groq RAG synthesis.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ResearchKnowledgeEngine()

# Mount UI static files if directory exists
UI_DIR = Path(__file__).resolve().parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the modern interactive web application."""
    index_path = UI_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
            )
    return HTMLResponse("<h1>Research Knowledge Engine</h1><p>UI files loading...</p>")

@app.get("/api/health")
async def health_check():
    """Health check endpoint for AWS load balancers, docker, and monitoring."""
    return JSONResponse({"status": "healthy", "service": "okf-rag"})


# ==================== Ingestion Endpoints ====================

@app.post("/api/ingest/pdf")
async def ingest_pdf(file: UploadFile = File(...)):
    """Ingest an uploaded PDF file with PyMuPDF."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    file_path = config.uploads_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = engine.ingest_pdf(str(file_path))
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF ingestion error: {str(e)}")

class URLIngestRequest(BaseModel):
    url: str

@app.post("/api/ingest/url")
async def ingest_url(req: URLIngestRequest):
    """Ingest web content from a URL."""
    if not req.url or not req.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A valid HTTP/HTTPS URL is required.")

    try:
        result = engine.ingest_url(req.url)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL ingestion error: {str(e)}")

class TextIngestRequest(BaseModel):
    title: str = "Research Note"
    content: str

@app.post("/api/ingest/text")
async def ingest_text(req: TextIngestRequest):
    """Ingest Markdown or plain text directly."""
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    try:
        result = engine.ingest_markdown_or_text(
            content_or_path=req.content,
            is_raw_text=True,
            title=req.title
        )
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text ingestion error: {str(e)}")

# ==================== Research Query Endpoint ====================

class QueryRequest(BaseModel):
    query: str
    session_id: str = "default_session"

@app.post("/api/research/query")
async def research_query(req: QueryRequest):
    """Execute research query using LangChain Hybrid Retriever and Groq RAG."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        answer = engine.research_query(req.query, session_id=req.session_id)
        return JSONResponse(answer.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research query error: {str(e)}")

# ==================== OKF & Graph Endpoints ====================

@app.get("/api/graph")
async def get_graph():
    """Fetch nodes and edges for the interactive Cytoscape knowledge graph."""
    return JSONResponse(engine.get_knowledge_graph())

@app.get("/api/concepts")
async def list_concepts():
    """List all extracted concepts in the MongoDB concepts collection."""
    concepts = engine.mongo_manager.list_concepts()
    # Format OKF Markdown+YAML preview for each
    for c in concepts:
        c["_id"] = str(c.get("_id", ""))
    return JSONResponse(concepts)

@app.get("/api/relationships")
async def list_relationships():
    """List all relationship edges in the MongoDB relationships collection."""
    rels = engine.mongo_manager.list_relationships()
    for r in rels:
        r["_id"] = str(r.get("_id", ""))
    return JSONResponse(rels)

@app.get("/api/sources")
async def list_sources():
    """List all sources in MongoDB sources collection."""
    sources = engine.mongo_manager.list_sources()
    for s in sources:
        s["_id"] = str(s.get("_id", ""))
    return JSONResponse(sources)

@app.get("/api/documents")
async def list_documents():
    """List all ingested documents."""
    docs = engine.mongo_manager.list_documents()
    for d in docs:
        d["_id"] = str(d.get("_id", ""))
    return JSONResponse(docs)

@app.get("/api/okf/concept/{concept_id}")
async def get_concept_okf(concept_id: str):
    """Retrieve full Markdown + YAML representation for a concept."""
    concepts = engine.mongo_manager.find_concepts_by_names_or_keywords([concept_id])
    if not concepts:
        # Try direct _id lookup
        c = engine.mongo_manager.db.concepts.find_one({"_id": concept_id})
        if c:
            concepts = [c]
    if not concepts:
        raise HTTPException(status_code=404, detail="Concept not found.")

    c_dict = dict(concepts[0])
    c_dict.pop("_id", None)
    c_obj = OKFConcept(**c_dict)
    md_yaml = OKFSerializer.concept_to_markdown_yaml(c_obj)
    return JSONResponse({"concept_id": concept_id, "name": c_obj.name, "okf_markdown": md_yaml})

@app.get("/api/storage/stats")
async def get_storage_stats():
    """Get statistics from MongoDB and Vector Store."""
    return JSONResponse(engine.get_system_stats())

@app.post("/api/storage/clear")
async def clear_storage():
    """Clear all documents, concepts, relationships, sources, and vector chunks."""
    result = engine.clear_all_data()
    return JSONResponse(result)

# ==================== Settings & Runtime Configuration ====================

class SettingsUpdateRequest(BaseModel):
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    extraction_model: Optional[str] = None
    mongodb_uri: Optional[str] = None


def _settings_payload() -> Dict[str, Any]:
    """Non-sensitive configuration state, as a plain dict.

    Returned directly by GET /api/settings and embedded in the POST response,
    so it must not be a Response object.
    """
    return {
        "groq_api_key_set": bool(config.groq_api_key),
        "groq_api_key_preview": f"...{config.groq_api_key[-4:]}" if len(config.groq_api_key) > 4 else "Not Set",
        "groq_api_key_source": config.groq_api_key_source,
        "groq_model": config.groq_model,
        "extraction_model": config.extraction_model,
        "mongodb_uri": config.mongodb_uri if config.mongodb_uri else "Embedded Persistent Store (Active)",
        "database_name": config.database_name,
        "embedding_model": config.embedding_model,
    }


def _fetch_groq_models(api_key: Optional[str] = None) -> Dict[str, Any]:
    """Ask Groq which models the configured key or candidate key can actually use."""
    key = (api_key or config.groq_api_key or "").strip()
    if not key:
        return {"models": [], "available": False, "status": "no_key", "reason": "No Groq API key configured."}

    try:
        import httpx
        res = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=12.0,
        )
        if res.status_code == 401:
            return {
                "models": [],
                "available": False,
                "status": "rejected",
                "reason": "Groq rejected this API key — it may be invalid, revoked, or expired.",
            }
        res.raise_for_status()
        data = res.json().get("data", [])
        # Groq lists speech and classifier models alongside chat models; only
        # chat-capable ids can serve extraction or RAG synthesis.
        NON_CHAT = ("whisper", "tts", "orpheus", "prompt-guard", "embed", "playai")
        models = sorted(
            (
                {
                    "id": m.get("id"),
                    "owned_by": m.get("owned_by", ""),
                    "context_window": m.get("context_window"),
                }
                for m in data
                if m.get("id")
                and m.get("active", True)
                and not any(tag in m["id"].lower() for tag in NON_CHAT)
            ),
            key=lambda m: m["id"],
        )
        return {"models": models, "available": True, "status": "ok", "reason": ""}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {
                "models": [],
                "available": False,
                "status": "rejected",
                "reason": "Groq rejected this API key — it may be invalid, revoked, or expired.",
            }
        return {"models": [], "available": False, "status": "error", "reason": f"Groq API returned HTTP {e.response.status_code}: {e}"}
    except Exception as e:
        return {"models": [], "available": False, "status": "unreachable", "reason": f"Could not reach Groq: {e}"}


def _select_best_groq_models(catalog_models: list) -> tuple[str, str]:
    """Given models returned by Groq, pick optimal synthesis and extraction models."""
    ids = [m["id"] for m in catalog_models if isinstance(m, dict) and "id" in m]
    if not ids:
        return "llama-3.3-70b-versatile", "llama-3.1-8b-instant"

    # Synthesis selection (prefer high capacity reasoning / chat models)
    synth_candidates = [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama3-70b-8192",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]
    synth_model = next((c for c in synth_candidates if c in ids), None)
    if not synth_model:
        synth_model = next((i for i in ids if any(k in i.lower() for k in ("70b", "120b", "27b", "llama"))), ids[0])

    # Extraction selection (prefer fast, high throughput, structured models)
    extract_candidates = [
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "openai/gpt-oss-safeguard-20b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "gemma2-9b-it",
    ]
    extract_model = next((c for c in extract_candidates if c in ids), None)
    if not extract_model:
        extract_model = next((i for i in ids if any(k in i.lower() for k in ("8b", "20b", "instant", "llama"))), ids[0])

    return synth_model, extract_model


@app.get("/api/settings")
async def get_settings():
    """Return non-sensitive configuration state."""
    return JSONResponse(_settings_payload())

@app.get("/api/settings/models")
async def list_groq_models(key: Optional[str] = None):
    """List the Groq models available to the configured API key or candidate key."""
    return JSONResponse(_fetch_groq_models(api_key=key))

@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """Update runtime settings (Groq key, models, MongoDB URI)."""
    updates = {}
    if req.groq_api_key is not None:
        key_clean = req.groq_api_key.strip()
        if key_clean:
            updates["groq_api_key"] = key_clean

    # Clean requested models, ignoring UI placeholder values
    if req.groq_model is not None and req.groq_model.strip():
        val = req.groq_model.strip()
        if not any(p in val for p in ("Enter an API", "loading", "unavailable", "…", "groq/compound")):
            updates["groq_model"] = val

    if req.extraction_model is not None and req.extraction_model.strip():
        val = req.extraction_model.strip()
        if not any(p in val for p in ("Enter an API", "loading", "unavailable", "…", "groq/compound")):
            updates["extraction_model"] = val

    if req.mongodb_uri is not None:
        updates["mongodb_uri"] = req.mongodb_uri.strip()

    # If the user is setting or modifying settings with an active key, validate against Groq
    active_key = updates.get("groq_api_key", config.groq_api_key)
    if active_key:
        catalog = _fetch_groq_models(api_key=active_key)
        if catalog.get("status") == "rejected":
            # If the user explicitly submitted this key, reject with clear guidance
            if "groq_api_key" in updates:
                raise HTTPException(
                    status_code=400,
                    detail="Groq rejected this API key (Invalid or Revoked Key). Please check your key at https://console.groq.com/keys"
                )
        elif catalog.get("available") and catalog.get("models"):
            known_ids = {m["id"] for m in catalog["models"]}
            synth_best, extract_best = _select_best_groq_models(catalog["models"])

            # Verify or auto-heal synthesis model
            req_synth = updates.get("groq_model", config.groq_model)
            if not req_synth or req_synth not in known_ids or req_synth == "groq/compound":
                updates["groq_model"] = synth_best

            # Verify or auto-heal extraction model
            req_extract = updates.get("extraction_model", config.extraction_model)
            if not req_extract or req_extract not in known_ids or req_extract == "groq/compound":
                updates["extraction_model"] = extract_best

    if not updates:
        return JSONResponse({"status": "unchanged", "settings": _settings_payload()})

    try:
        config.update_settings(**updates)
        engine.refresh_clients()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not apply settings: {e}")

    return JSONResponse({"status": "updated", "settings": _settings_payload()})

@app.delete("/api/settings/groq-key")
async def delete_groq_key():
    """Forget the stored Groq API key."""
    config.clear_groq_api_key()
    engine.refresh_clients()
    return JSONResponse({"status": "cleared", "settings": _settings_payload()})
