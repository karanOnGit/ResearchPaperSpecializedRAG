import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.config import config
from app.okf.models import (
    ResearchAnswer,
    OKFSource,
    OKFConcept,
    CitationItem,
    ConfidenceProvenance,
    DocumentChunk,
    OKFProvenance
)
from app.retriever.hybrid_retriever import HybridRetrievalResult

class GroqRAGEngine:
    """Groq LLM RAG engine orchestrating grounded research synthesis,

    generating Answer, Sources, Citations, Related Concepts, and Confidence/Provenance.
    """

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.groq_api_key
        self.model = model or config.groq_model

    def generate_research_answer(
        self,
        query: str,
        retrieval_result: HybridRetrievalResult
    ) -> ResearchAnswer:
        """Run Groq RAG synthesis over hybrid retrieved chunks & OKF concepts."""
        if not retrieval_result.chunks and not retrieval_result.concepts:
            return ResearchAnswer(
                query=query,
                answer="No relevant documents or concepts were found in the knowledge base. Please ingest documents, URLs, or markdown notes first.",
                sources=[],
                citations=[],
                related_concepts=[],
                confidence_provenance=ConfidenceProvenance(
                    score=0.0,
                    rating="Low",
                    rationale="No matching evidence retrieved from MongoDB or Vector Index.",
                    sources_consulted=0,
                    concepts_linked=0
                ),
                retrieved_chunks=[],
            )

        if self.api_key:
            try:
                return self._generate_with_groq(query, retrieval_result)
            except Exception as e:
                print(f"[GroqRAG] Groq API execution failed: {e}. Falling back to grounded synthesis.")
                return self._generate_with_grounded_heuristic(query, retrieval_result)
        else:
            return self._generate_with_grounded_heuristic(query, retrieval_result)

    def _generate_with_groq(
        self,
        query: str,
        retrieval_result: HybridRetrievalResult
    ) -> ResearchAnswer:
        from groq import Groq

        client = Groq(api_key=self.api_key)

        # Prepare context
        context_chunks_text = []
        citation_pool: List[Dict[str, Any]] = []

        for idx, chunk in enumerate(retrieval_result.chunks[:6]):
            cite_id = idx + 1
            source_path = chunk.metadata.get("source_path_or_url", "")
            context_chunks_text.append(
                f"[{cite_id}] Source: '{chunk.source_title}' (Page {chunk.page_number or 'N/A'}):\n{chunk.cleaned_content}"
            )
            citation_pool.append({
                "citation_id": cite_id,
                "quote": chunk.cleaned_content[:200] + "...",
                "source_id": chunk.doc_id,
                "source_title": chunk.source_title,
                "source_url_or_path": source_path,
                "page": chunk.page_number
            })

        # Concept graph context
        concept_context_lines = []
        for c in retrieval_result.concepts[:8]:
            c_name = c.get("name", "")
            c_cat = c.get("category", "Entity")
            c_def = c.get("definition", "")
            concept_context_lines.append(f"- **{c_name}** ({c_cat}): {c_def}")

        rel_context_lines = []
        for r in retrieval_result.relationships[:10]:
            rel_context_lines.append(f"- {r.get('source')} -[{r.get('relation_type')}]-> {r.get('target')}: {r.get('description')}")

        prompt = f"""You are the Groq Research Knowledge Engine. Answer the user's research query with rigorous academic clarity, grounded strictly in the provided Context and Knowledge Graph.

User Query:
\"{query}\"

Retrieved Text Chunks:
{chr(10).join(context_chunks_text)}

Knowledge Graph Concepts:
{chr(10).join(concept_context_lines) if concept_context_lines else "None"}

Knowledge Graph Relationships:
{chr(10).join(rel_context_lines) if rel_context_lines else "None"}

Requirements:
1. Provide a detailed, highly structured, authoritative scientific synthesis.
2. Ground every major factual statement using inline citation markers like [1], [2] referencing the retrieved text chunks.
3. Assess the provenance and confidence level (High, Medium, or Low) based on empirical grounding.
4. Extract direct verbatim quotes supporting each citation.

Return ONLY a valid JSON object matching this schema:
{{
  "answer": "Comprehensive answer with inline citations like [1] and [2]...",
  "citations": [
    {{
      "citation_id": 1,
      "quote": "exact verbatim excerpt supporting citation 1",
      "source_title": "Title of source"
    }}
  ],
  "confidence": {{
    "score": 0.95,
    "rating": "High|Medium|Low",
    "rationale": "Explanation of empirical grounding and source provenance"
  }}
}}
"""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a research knowledge engine synthesizing grounded scientific answers in JSON format."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=2500,
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        answer_text = data.get("answer", "")
        raw_citations = data.get("citations", [])
        raw_conf = data.get("confidence", {})

        # Build CitationItems
        citations: List[CitationItem] = []
        for rc in raw_citations:
            cid = rc.get("citation_id", 1)
            # Find matching chunk
            matching_pool = next((p for p in citation_pool if p["citation_id"] == cid), None)
            quote = rc.get("quote", "") or (matching_pool["quote"] if matching_pool else "")
            
            citations.append(CitationItem(
                citation_id=cid,
                quote=quote,
                source_id=matching_pool["source_id"] if matching_pool else "",
                source_title=matching_pool["source_title"] if matching_pool else rc.get("source_title", ""),
                source_url_or_path=matching_pool["source_url_or_path"] if matching_pool else "",
                page=matching_pool["page"] if matching_pool else None
            ))

        # Build Sources list
        sources: List[OKFSource] = []
        seen_sources = set()
        for s in retrieval_result.sources:
            sid = s.get("_id") or s.get("id", "")
            if sid not in seen_sources:
                seen_sources.add(sid)
                sources.append(OKFSource(
                    id=sid,
                    title=s.get("title", "Untitled"),
                    source_type=s.get("source_type", "document"),
                    source_path_or_url=s.get("source_path_or_url", ""),
                    author=s.get("author", ""),
                    published_date=s.get("published_date", ""),
                    summary=s.get("summary", ""),
                    total_chunks=s.get("total_chunks", 0),
                    total_concepts=s.get("total_concepts", 0),
                ))

        # Build Related Concepts list
        related_concepts: List[OKFConcept] = []
        for c in retrieval_result.concepts[:8]:
            prov_raw = c.get("provenance", {})
            prov = OKFProvenance(
                source_id=prov_raw.get("source_id", ""),
                source_title=prov_raw.get("source_title", ""),
                source_url=prov_raw.get("source_url", ""),
                page_number=prov_raw.get("page_number"),
                section=prov_raw.get("section"),
                extractor=prov_raw.get("extractor", "groq"),
                confidence=float(prov_raw.get("confidence", 0.9)),
            )
            related_concepts.append(OKFConcept(
                id=c.get("_id") or c.get("id", ""),
                name=c.get("name", ""),
                category=c.get("category", "Entity"),
                definition=c.get("definition", ""),
                aliases=c.get("aliases", []),
                provenance=prov,
                mention_count=c.get("mention_count", 1),
                tags=c.get("tags", []),
            ))

        conf_obj = ConfidenceProvenance(
            score=float(raw_conf.get("score", 0.92)),
            rating=raw_conf.get("rating", "High"),
            rationale=raw_conf.get("rationale", "Synthesis grounded directly in retrieved vector chunks and OKF concept graph."),
            sources_consulted=len(sources),
            concepts_linked=len(related_concepts),
        )

        return ResearchAnswer(
            query=query,
            answer=answer_text,
            sources=sources,
            citations=citations,
            related_concepts=related_concepts,
            confidence_provenance=conf_obj,
            retrieved_chunks=retrieval_result.chunks,
        )

    def _generate_with_grounded_heuristic(
        self,
        query: str,
        retrieval_result: HybridRetrievalResult
    ) -> ResearchAnswer:
        """Grounded synthesis fallback when Groq API key is not configured."""
        top_chunks = retrieval_result.chunks[:4]
        answer_parts = []
        citations: List[CitationItem] = []
        cite_id = 1

        answer_parts.append(f"Based on the knowledge base objects retrieved for **\"{query}\"**:\n")

        for idx, chunk in enumerate(top_chunks):
            # Take key sentences from the chunk
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chunk.cleaned_content) if len(s.strip()) > 20]
            summary_sentence = sentences[0] if sentences else chunk.cleaned_content[:150]
            
            answer_parts.append(f"- {summary_sentence} `[{cite_id}]`")
            
            source_path = chunk.metadata.get("source_path_or_url", "")
            citations.append(CitationItem(
                citation_id=cite_id,
                quote=summary_sentence,
                source_id=chunk.doc_id,
                source_title=chunk.source_title,
                source_url_or_path=source_path,
                page=chunk.page_number
            ))
            cite_id += 1

        if retrieval_result.concepts:
            answer_parts.append("\n### Conceptual Grounding")
            for c in retrieval_result.concepts[:4]:
                answer_parts.append(f"- **{c.get('name')}** (`{c.get('category', 'Entity')}`): {c.get('definition')}")

        if retrieval_result.relationships:
            answer_parts.append("\n### Identified Relationships")
            for r in retrieval_result.relationships[:4]:
                answer_parts.append(f"- **{r.get('source')}** `{r.get('relation_type')}` **{r.get('target')}**: {r.get('description')}")

        full_answer = "\n".join(answer_parts)

        # Sources
        sources: List[OKFSource] = []
        seen = set()
        for s in retrieval_result.sources:
            sid = s.get("_id") or s.get("id", "")
            if sid not in seen:
                seen.add(sid)
                sources.append(OKFSource(
                    id=sid,
                    title=s.get("title", "Document"),
                    source_type=s.get("source_type", "document"),
                    source_path_or_url=s.get("source_path_or_url", ""),
                    author=s.get("author", ""),
                    published_date=s.get("published_date", ""),
                    summary=s.get("summary", ""),
                    total_chunks=s.get("total_chunks", 0),
                    total_concepts=s.get("total_concepts", 0),
                ))

        # Related concepts
        related_concepts: List[OKFConcept] = []
        for c in retrieval_result.concepts[:6]:
            prov_raw = c.get("provenance", {})
            prov = OKFProvenance(
                source_id=prov_raw.get("source_id", ""),
                source_title=prov_raw.get("source_title", ""),
                source_url=prov_raw.get("source_url", ""),
                page_number=prov_raw.get("page_number"),
                section=prov_raw.get("section"),
                extractor=prov_raw.get("extractor", "heuristic"),
                confidence=float(prov_raw.get("confidence", 0.85)),
            )
            related_concepts.append(OKFConcept(
                id=c.get("_id") or c.get("id", ""),
                name=c.get("name", ""),
                category=c.get("category", "Entity"),
                definition=c.get("definition", ""),
                aliases=c.get("aliases", []),
                provenance=prov,
                mention_count=c.get("mention_count", 1),
                tags=c.get("tags", []),
            ))

        conf = ConfidenceProvenance(
            score=0.88,
            rating="High" if len(sources) > 0 else "Medium",
            rationale="Deterministic grounded retrieval from MongoDB Concept Graph and Vector Index.",
            sources_consulted=len(sources),
            concepts_linked=len(related_concepts)
        )

        return ResearchAnswer(
            query=query,
            answer=full_answer,
            sources=sources,
            citations=citations,
            related_concepts=related_concepts,
            confidence_provenance=conf,
            retrieved_chunks=retrieval_result.chunks,
        )
