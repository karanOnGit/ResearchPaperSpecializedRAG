import os
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.config import config
from app.ingestion.pdf_loader import PDFLoader
from app.ingestion.web_loader import WebLoader
from app.ingestion.markdown_loader import MarkdownLoader
from app.processing.chunker import TextChunker
from app.extraction.groq_extractor import GroqKnowledgeExtractor
from app.okf.models import OKFSource, OKFConcept, OKFRelationship, OKFDocumentBundle, ResearchAnswer
from app.okf.serializer import OKFSerializer
from app.storage.mongo_manager import MongoManager
from app.storage.vector_manager import VectorManager
from app.retriever.hybrid_retriever import OKFHybridRetriever
from app.rag.groq_rag import GroqRAGEngine

class ResearchKnowledgeEngine:
    """The central unified Research Knowledge Engine coordinator.

    Coordinates Ingestion -> Cleaning & Chunking -> Groq Extraction ->
    OKF Layer (Markdown+YAML) -> Dual Storage (MongoDB + Vector Index) ->
    LangChain Hybrid Retriever -> Groq RAG -> Research Answer.
    """

    def __init__(self):
        self.config = config
        self.mongo_manager = MongoManager()
        self.vector_manager = VectorManager()
        self.chunker = TextChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap
        )
        self.extractor = GroqKnowledgeExtractor(
            api_key=self.config.groq_api_key,
            model=self.config.extraction_model
        )
        self.retriever = OKFHybridRetriever(
            mongo_mgr=self.mongo_manager,
            vector_mgr=self.vector_manager
        )
        self.rag_engine = GroqRAGEngine(
            api_key=self.config.groq_api_key,
            model=self.config.groq_model
        )

    def refresh_clients(self):
        """Reload extractor and RAG engine when settings (e.g. Groq API key) change."""
        self.extractor = GroqKnowledgeExtractor(
            api_key=self.config.groq_api_key,
            model=self.config.extraction_model
        )
        self.rag_engine = GroqRAGEngine(
            api_key=self.config.groq_api_key,
            model=self.config.groq_model
        )

    # ==================== Document Ingestion Pipeline ====================

    def ingest_pdf(self, file_path: str) -> Dict[str, Any]:
        """Ingest a PDF using PyMuPDF."""
        loader = PDFLoader(file_path)
        doc_data = loader.load()
        return self._process_and_store_document(doc_data)

    def ingest_url(self, url: str) -> Dict[str, Any]:
        """Ingest web content using Web Loader."""
        loader = WebLoader(url)
        doc_data = loader.load()
        return self._process_and_store_document(doc_data)

    def ingest_markdown_or_text(self, content_or_path: str, is_raw_text: bool = False, title: str = "") -> Dict[str, Any]:
        """Ingest Markdown or raw text notes."""
        loader = MarkdownLoader(content_or_path, is_raw_text=is_raw_text, title=title)
        doc_data = loader.load()
        return self._process_and_store_document(doc_data)

    def _process_and_store_document(self, doc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run the full ingestion -> chunking -> extraction -> OKF -> dual storage pipeline."""
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"
        title = doc_data.get("title", "Untitled Document")
        source_type = doc_data.get("source_type", "unknown")
        source_path_or_url = doc_data.get("source_path_or_url", "")

        # 1. Text Cleaning & Chunking
        chunks = self.chunker.chunk_document(doc_data, doc_id=doc_id)

        # 2. Groq LLM Knowledge Extraction
        concepts, relationships = self.extractor.extract_from_chunks(
            chunks=chunks,
            doc_id=doc_id,
            source_title=title,
            source_url_or_path=source_path_or_url
        )

        # 3. Create OKF Source & Document Bundle
        source_obj = OKFSource(
            id=doc_id,
            title=title,
            source_type=source_type,
            source_path_or_url=source_path_or_url,
            author=doc_data.get("author", ""),
            published_date=doc_data.get("published_date", ""),
            summary=f"Ingested {source_type} document containing {len(chunks)} chunks and {len(concepts)} extracted concepts.",
            total_chunks=len(chunks),
            total_concepts=len(concepts),
            metadata=doc_data.get("metadata", {})
        )

        # 4. Export OKF Markdown + YAML artifact
        okf_md_yaml = OKFSerializer.source_to_markdown_yaml(
            source=source_obj,
            concepts=concepts,
            relationships=relationships
        )
        okf_file_path = self.config.okf_export_dir / f"{doc_id}_{re_clean_filename(title)}.okf.md"
        with open(okf_file_path, "w", encoding="utf-8") as f:
            f.write(okf_md_yaml)

        # 5. Dual Storage - MongoDB
        # a) Save document metadata
        self.mongo_manager.save_document({
            "_id": doc_id,
            "title": title,
            "source_type": source_type,
            "source_path_or_url": source_path_or_url,
            "total_chunks": len(chunks),
            "total_concepts": len(concepts),
            "total_relationships": len(relationships),
            "created_at": datetime.utcnow().isoformat(),
            "okf_path": str(okf_file_path),
            "metadata": doc_data.get("metadata", {}),
        })
        # b) Save Source
        self.mongo_manager.save_source(source_obj)
        # c) Save Concepts
        self.mongo_manager.save_concepts(concepts)
        # d) Save Relationships
        self.mongo_manager.save_relationships(relationships)

        # 6. Dual Storage - Vector Index (ChromaDB)
        self.vector_manager.add_chunks(chunks)

        return {
            "status": "success",
            "doc_id": doc_id,
            "title": title,
            "source_type": source_type,
            "chunks_count": len(chunks),
            "concepts_count": len(concepts),
            "relationships_count": len(relationships),
            "okf_export_path": str(okf_file_path),
            "concepts": [c.model_dump() for c in concepts],
            "relationships": [r.model_dump() for r in relationships],
        }

    # ==================== Research Query Pipeline ====================

    def research_query(self, query: str, session_id: str = "default_session") -> ResearchAnswer:
        """Execute end-to-end research query through Hybrid Retriever & Groq RAG."""
        # 1. Hybrid Retrieval (Vector + MongoDB Graph)
        retrieval_result = self.retriever.hybrid_retrieve(query)

        # 2. Groq LLM RAG Synthesis
        research_answer = self.rag_engine.generate_research_answer(query, retrieval_result)

        # 3. Store turn into MongoDB chat_history
        self.mongo_manager.save_chat_turn(
            session_id=session_id,
            query=query,
            answer_data=research_answer.model_dump()
        )

        return research_answer

    # ==================== Graph & OKF Visualization ====================

    def get_knowledge_graph(self) -> Dict[str, Any]:
        """Generate node and edge data for interactive graph visualization."""
        concepts = self.mongo_manager.list_concepts(limit=150)
        relationships = self.mongo_manager.list_relationships(limit=250)

        nodes = []
        node_ids = set()

        # Add concept nodes
        for c in concepts:
            c_name = c.get("name")
            if c_name and c_name not in node_ids:
                node_ids.add(c_name)
                nodes.append({
                    "id": c_name,
                    "label": c_name,
                    "type": "concept",
                    "category": c.get("category", "Entity"),
                    "definition": c.get("definition", ""),
                    "mention_count": c.get("mention_count", 1),
                })

        edges = []
        for r in relationships:
            src = r.get("source")
            tgt = r.get("target")
            if src and tgt:
                # Ensure src and tgt nodes exist
                for endpoint in [src, tgt]:
                    if endpoint not in node_ids:
                        node_ids.add(endpoint)
                        nodes.append({
                            "id": endpoint,
                            "label": endpoint,
                            "type": "concept",
                            "category": "Entity",
                            "definition": "",
                            "mention_count": 1,
                        })

                edges.append({
                    "id": r.get("_id") or r.get("id"),
                    "source": src,
                    "target": tgt,
                    "label": r.get("relation_type", "RELATED_TO"),
                    "description": r.get("description", ""),
                    "evidence": r.get("evidence_quote", ""),
                })

        return {"nodes": nodes, "edges": edges}

    def get_system_stats(self) -> Dict[str, Any]:
        """Aggregate stats from MongoDB and Vector Index."""
        mongo_stats = self.mongo_manager.get_stats()
        vector_stats = self.vector_manager.get_stats()
        return {
            "mongodb": mongo_stats,
            "vector_index": vector_stats,
            "groq_model": self.config.groq_model,
            "groq_api_key_configured": bool(self.config.groq_api_key),
            "database_name": self.config.database_name,
        }

    def clear_all_data(self) -> Dict[str, Any]:
        """Purge all documents, concepts, relationships, sources, and vector chunks."""
        self.mongo_manager.clear_all()
        self.vector_manager.clear_all()
        # Clean local exports and uploads
        for f in self.config.okf_export_dir.glob("*.md"):
            try:
                f.unlink()
            except Exception:
                pass
        for f in self.config.uploads_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
        return {"status": "cleared", "stats": self.get_system_stats()}

def re_clean_filename(name: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name.lower())[:40]
