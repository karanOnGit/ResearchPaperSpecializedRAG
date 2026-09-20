import re
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.storage.mongo_manager import MongoManager
from app.storage.vector_manager import VectorManager
from app.okf.models import OKFConcept, OKFRelationship, OKFSource, DocumentChunk

class HybridRetrievalResult(BaseModel):
    query: str
    chunks: List[DocumentChunk]
    concepts: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    fused_scores: Dict[str, float] = Field(default_factory=dict)

class OKFHybridRetriever(BaseRetriever):
    """LangChain Hybrid Retriever combining Vector Index (dense semantic search)

    and MongoDB (concept & 1-hop relationship graph lookup) with Reciprocal Rank Fusion.
    """
    mongo_manager: Any = Field(default=None)
    vector_manager: Any = Field(default=None)
    top_k_chunks: int = 6
    top_k_concepts: int = 10
    graph_expansion_hops: int = 1

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, mongo_mgr: MongoManager = None, vector_mgr: VectorManager = None, **kwargs):
        super().__init__(
            mongo_manager=mongo_mgr or MongoManager(),
            vector_manager=vector_mgr or VectorManager(),
            **kwargs
        )

    def _extract_query_keywords(self, query: str) -> List[str]:
        """Extract candidate concept terms and key phrases from user query."""
        terms = []
        # Multi-word capital phrases
        capital_matches = re.findall(r'\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*)\b', query)
        terms.extend(capital_matches)

        # Lowercase keywords >= 4 characters
        words = re.findall(r'\b[a-zA-Z]{4,}\b', query)
        stopwords = {
            "what", "when", "where", "which", "with", "about", "could", "would",
            "should", "their", "there", "these", "those", "explain", "describe",
            "details", "concept", "retrieve", "system", "please", "using", "between"
        }
        for w in words:
            if w.lower() not in stopwords:
                terms.append(w)

        # De-duplicate while preserving order
        unique_terms = []
        seen = set()
        for t in terms:
            t_low = t.lower()
            if t_low not in seen:
                seen.add(t_low)
                unique_terms.append(t)
        return unique_terms

    def hybrid_retrieve(self, query: str) -> HybridRetrievalResult:
        """Core hybrid retrieval algorithm merging vector chunks + MongoDB concept graph."""
        query_keywords = self._extract_query_keywords(query)

        # 1. Vector Search: dense semantic chunk similarity
        vector_results: List[Tuple[DocumentChunk, float]] = self.vector_manager.search(
            query=query,
            top_k=self.top_k_chunks
        )

        # 2. MongoDB Concept Search: match by keywords, name, aliases, or definition
        matched_concepts = self.mongo_manager.find_concepts_by_names_or_keywords(query_keywords)
        matched_concept_names = [c["name"] for c in matched_concepts]

        # Also pull concepts tagged in the retrieved vector chunks
        for chunk, _ in vector_results:
            for c_name in chunk.concepts:
                if c_name not in matched_concept_names:
                    matched_concept_names.append(c_name)

        # If any concepts found, retrieve their 1-hop relationships from MongoDB
        connected_relationships = []
        if matched_concept_names:
            connected_relationships = self.mongo_manager.get_related_edges(matched_concept_names[:self.top_k_concepts])

        # 3. Reciprocal Rank Fusion / Scoring:
        # Boost chunks that contain confirmed concepts or relationship endpoints
        fused_scores = {}
        chunk_map: Dict[str, DocumentChunk] = {}

        for rank, (chunk, v_score) in enumerate(vector_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            # Vector reciprocal rank score
            rr_score = 1.0 / (60 + rank + 1)
            # Concept density boost
            concept_overlap = sum(1 for c in chunk.concepts if c in matched_concept_names)
            boost = 1.0 + (0.25 * concept_overlap)
            fused_scores[cid] = (v_score * 0.6 + rr_score * 40.0) * boost

        # Sort chunks by fused score
        sorted_chunk_ids = sorted(fused_scores.keys(), key=lambda cid: fused_scores[cid], reverse=True)
        ranked_chunks = [chunk_map[cid] for cid in sorted_chunk_ids]

        # 4. Fetch source documents referenced by the retrieved chunks
        source_ids = list(set(c.doc_id for c in ranked_chunks if c.doc_id))
        sources = []
        for sid in source_ids:
            src = self.mongo_manager.get_source(sid) or self.mongo_manager.get_document(sid)
            if src:
                # Remove mongo _id formatting if necessary
                src_clean = dict(src)
                src_clean["_id"] = str(src_clean.get("_id", sid))
                sources.append(src_clean)

        return HybridRetrievalResult(
            query=query,
            chunks=ranked_chunks,
            concepts=matched_concepts,
            relationships=connected_relationships,
            sources=sources,
            fused_scores=fused_scores
        )

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """LangChain standard retrieval interface implementation."""
        result = self.hybrid_retrieve(query)
        docs = []
        for chunk in result.chunks:
            metadata = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "source_title": chunk.source_title,
                "source_type": chunk.source_type,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "fused_score": result.fused_scores.get(chunk.chunk_id, 0.0),
                "concepts": chunk.concepts
            }
            docs.append(Document(page_content=chunk.cleaned_content, metadata=metadata))
        return docs
