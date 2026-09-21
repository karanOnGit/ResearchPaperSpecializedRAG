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
    top_k_chunks: int = 15
    top_k_final: int = 6
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
        """Extract candidate concept terms, actions, and key phrases from user query."""
        terms = []
        # Multi-word capital phrases
        capital_matches = re.findall(r'\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*)\b', query)
        terms.extend(capital_matches)

        # Words >= 3 characters (including action stems like 'who', 'does', 'quench', etc.)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', query)
        stopwords = {
            "the", "and", "for", "with", "about", "could", "would",
            "should", "their", "there", "these", "those", "explain", "describe",
            "details", "concept", "retrieve", "system", "please", "using", "between", "from"
        }
        for w in words:
            if w.lower() not in stopwords:
                terms.append(w)
                # Also include stem if word ends with 'es', 's', 'ing', 'ed'
                w_low = w.lower()
                if w_low.endswith("es") and len(w_low) > 4:
                    terms.append(w_low[:-2])
                elif w_low.endswith("ing") and len(w_low) > 5:
                    terms.append(w_low[:-3])
                elif w_low.endswith("ed") and len(w_low) > 4:
                    terms.append(w_low[:-2])
                elif w_low.endswith("s") and len(w_low) > 3:
                    terms.append(w_low[:-1])

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
        """Enhanced hybrid retrieval combining dense vector search, direct graph triples, and lexical ranking."""
        query_keywords = self._extract_query_keywords(query)
        query_lower = query.lower()

        # 1. Broad Vector Candidate Search (top 15 chunks)
        vector_results: List[Tuple[DocumentChunk, float]] = self.vector_manager.search(
            query=query,
            top_k=self.top_k_chunks
        )

        # 2. Direct Relationship Triple Search:
        # Search MongoDB relationships directly by predicate, source, target, or description
        direct_triples = self.mongo_manager.find_relationships_by_predicate_or_terms(query_keywords, limit=20)

        # 3. Concept Search: match by keywords, name, aliases, or definition
        matched_concepts = self.mongo_manager.find_concepts_by_names_or_keywords(query_keywords)
        matched_concept_names = [c["name"] for c in matched_concepts]

        # Also pull concepts tagged in the retrieved vector chunks
        for chunk, _ in vector_results:
            for c_name in chunk.concepts:
                if c_name not in matched_concept_names:
                    matched_concept_names.append(c_name)

        # Retrieve 1-hop relationships for matched concepts
        connected_relationships = []
        if matched_concept_names:
            connected_relationships = self.mongo_manager.get_related_edges(matched_concept_names[:self.top_k_concepts])

        # Merge and de-duplicate all retrieved relationships
        all_relationships: List[Dict[str, Any]] = []
        seen_rel_sigs = set()
        for r in (direct_triples + connected_relationships):
            sig = (r.get("source", "").strip().title(), r.get("relation_type", "").strip().upper(), r.get("target", "").strip().title())
            if sig not in seen_rel_sigs:
                seen_rel_sigs.add(sig)
                all_relationships.append(r)

        # 4. Multi-Factor Re-Ranking & Fusion:
        fused_scores = {}
        chunk_map: Dict[str, DocumentChunk] = {}

        # Collect triple keywords for boosting
        triple_terms = set()
        for r in all_relationships:
            src = r.get("source", "").lower()
            tgt = r.get("target", "").lower()
            rel = r.get("relation_type", "").lower()
            triple_terms.update(src.split())
            triple_terms.update(tgt.split())
            triple_terms.update(rel.split())

        for rank, (chunk, v_score) in enumerate(vector_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            chunk_text_lower = chunk.cleaned_content.lower()

            # Base vector reciprocal rank score
            rr_score = 1.0 / (60 + rank + 1)

            # Lexical keyword coverage in chunk
            keyword_hits = sum(1 for kw in query_keywords if kw.lower() in chunk_text_lower)
            lexical_score = keyword_hits / max(1, len(query_keywords))

            # Graph triple alignment boost: does chunk contain subject + relation + target from matched triples?
            triple_match_boost = 1.0
            for r in all_relationships:
                r_src = r.get("source", "").lower()
                r_tgt = r.get("target", "").lower()
                r_ev = r.get("evidence_quote", "").lower()
                if (r_src in chunk_text_lower and r_tgt in chunk_text_lower) or (r_ev and r_ev in chunk_text_lower):
                    triple_match_boost += 1.8
                    break
                elif r_src in chunk_text_lower or r_tgt in chunk_text_lower:
                    triple_match_boost += 0.4

            # Section heading alignment boost
            section_lower = (chunk.section or "").lower()
            section_boost = 1.0
            if any(kw.lower() in section_lower for kw in query_keywords if len(kw) > 3):
                section_boost += 0.5
            if "relationship" in section_lower and ("quench" in query_lower or "does" in query_lower or "who" in query_lower or "relat" in query_lower):
                section_boost += 1.2
            if "action" in section_lower and ("who" in query_lower or "does" in query_lower or "what" in query_lower):
                section_boost += 1.0

            # Composite fused score
            composite = (v_score * 0.4 + rr_score * 30.0 + lexical_score * 25.0) * triple_match_boost * section_boost
            fused_scores[cid] = composite

        # Sort chunks by composite score and take top_k_final
        sorted_chunk_ids = sorted(fused_scores.keys(), key=lambda cid: fused_scores[cid], reverse=True)
        ranked_chunks = [chunk_map[cid] for cid in sorted_chunk_ids[:self.top_k_final]]

        # 5. Fetch source documents referenced by the retrieved chunks
        source_ids = list(set(c.doc_id for c in ranked_chunks if c.doc_id))
        sources = []
        for sid in source_ids:
            src = self.mongo_manager.get_source(sid) or self.mongo_manager.get_document(sid)
            if src:
                src_clean = dict(src)
                src_clean["_id"] = str(src_clean.get("_id", sid))
                sources.append(src_clean)

        return HybridRetrievalResult(
            query=query,
            chunks=ranked_chunks,
            concepts=matched_concepts,
            relationships=all_relationships,
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
