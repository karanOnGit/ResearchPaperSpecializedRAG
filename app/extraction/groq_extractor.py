import json
import re
import uuid
from typing import List, Dict, Any, Tuple
from app.config import config
from app.okf.models import OKFConcept, OKFRelationship, OKFProvenance, DocumentChunk

class GroqKnowledgeExtractor:
    """Knowledge extraction engine using Groq LLM (with heuristic NLP fallback)."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.groq_api_key
        self.model = model or config.extraction_model

    def extract_from_chunks(
        self,
        chunks: List[DocumentChunk],
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Extract typed concepts and relationships across document chunks."""
        all_concepts: Dict[str, OKFConcept] = {}
        all_relationships: List[OKFRelationship] = []

        # Process key representative chunks with Groq (up to 2 chunks to stay within 1000 OTPM limit)
        # and supplement remaining chunks with heuristic extraction
        groq_chunks_limit = 2
        groq_chunks_processed = 0

        for idx, chunk in enumerate(chunks):
            # Use Groq for first 2 chunks or key chunks
            if self.api_key and groq_chunks_processed < groq_chunks_limit:
                try:
                    concepts, relationships = self._extract_from_single_chunk(
                        chunk=chunk,
                        doc_id=doc_id,
                        source_title=source_title,
                        source_url_or_path=source_url_or_path,
                    )
                    groq_chunks_processed += 1
                except Exception:
                    concepts, relationships = self._extract_with_heuristics(
                        chunk=chunk,
                        doc_id=doc_id,
                        source_title=source_title,
                        source_url_or_path=source_url_or_path,
                    )
            else:
                concepts, relationships = self._extract_with_heuristics(
                    chunk=chunk,
                    doc_id=doc_id,
                    source_title=source_title,
                    source_url_or_path=source_url_or_path,
                )

            # Merge concepts
            for c in concepts:
                norm_name = c.name.strip().title()
                if norm_name in all_concepts:
                    existing = all_concepts[norm_name]
                    existing.mention_count += 1
                    # Merge aliases
                    for a in c.aliases:
                        if a not in existing.aliases:
                            existing.aliases.append(a)
                    # Append relationships
                    for r in c.relationships:
                        existing.relationships.append(r)
                else:
                    c.name = norm_name
                    all_concepts[norm_name] = c

            all_relationships.extend(relationships)

        # De-duplicate relationships
        unique_rels: List[OKFRelationship] = []
        rel_signatures = set()
        for r in all_relationships:
            sig = (r.source.strip().title(), r.relation_type.strip().upper(), r.target.strip().title())
            if sig not in rel_signatures:
                rel_signatures.add(sig)
                unique_rels.append(r)

        return list(all_concepts.values()), unique_rels

    def _extract_from_single_chunk(
        self,
        chunk: DocumentChunk,
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Extract concepts and relationships from one chunk."""
        if self.api_key:
            try:
                return self._extract_with_groq(chunk, doc_id, source_title, source_url_or_path)
            except Exception as e:
                print(f"[GroqExtractor] Groq API call failed: {e}. Using heuristic fallback.")
                return self._extract_with_heuristics(chunk, doc_id, source_title, source_url_or_path)
        else:
            return self._extract_with_heuristics(chunk, doc_id, source_title, source_url_or_path)

    def _extract_with_groq(
        self,
        chunk: DocumentChunk,
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Use Groq API to extract structured knowledge."""
        from groq import Groq

        client = Groq(api_key=self.api_key)

        prompt = f"""You are a research knowledge extraction engine specializing in the Open Knowledge Format (OKF).
Analyze the following text chunk from "{source_title}".
Extract all key TYPED CONCEPTS and DIRECT RELATIONSHIPS between concepts.

Guidelines:
1. Concept Categories: Entity, Mechanism, Protocol, Metric, Architecture, Theory, Tool, Dataset.
2. Concept Definition: Concise, factual 1-2 sentence definition grounded in the text.
3. Relationships: Identify connections using standard types:
   IMPLEMENTS, USES, EXTENDS, EVALUATED_ON, ENABLES, CAUSES, PART_OF, CONTRADICTS.
4. Quote: Include exact short verbatim quote from the text supporting each relationship.

Text Chunk:
\"\"\"{chunk.cleaned_content}\"\"\"

Return ONLY valid JSON matching this schema:
{{
  "concepts": [
    {{
      "name": "Concept Name",
      "category": "Architecture|Mechanism|Tool|Entity|Metric|Theory",
      "definition": "Clear concise definition.",
      "aliases": ["Alternative Name"],
      "confidence": 0.95
    }}
  ],
  "relationships": [
    {{
      "source": "Concept A",
      "target": "Concept B",
      "relation_type": "USES|IMPLEMENTS|PART_OF|ENABLES",
      "description": "How A and B relate",
      "evidence_quote": "verbatim quote from text"
    }}
  ]
}}
"""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You extract structured knowledge in JSON for the OKF layer."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""
        clean_content = content.strip()
        if clean_content.startswith("```"):
            clean_content = re.sub(r"^```(?:json)?\s*", "", clean_content)
            clean_content = re.sub(r"\s*```$", "", clean_content)

        if not clean_content or not clean_content.startswith("{"):
            # Try to find JSON object substring
            json_match = re.search(r"\{.*\}", clean_content, re.DOTALL)
            if json_match:
                clean_content = json_match.group(0)
            else:
                return self._extract_with_heuristics(chunk, doc_id, source_title, source_url_or_path)

        try:
            data = json.loads(clean_content)
        except Exception:
            return self._extract_with_heuristics(chunk, doc_id, source_title, source_url_or_path)

        raw_concepts = data.get("concepts", [])
        raw_rels = data.get("relationships", [])

        concepts: List[OKFConcept] = []
        relationships: List[OKFRelationship] = []

        for c_idx, rc in enumerate(raw_concepts):
            c_name = rc.get("name", "").strip().title()
            if not c_name:
                continue
            c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', c_name.lower())[:32]}"
            
            prov = OKFProvenance(
                source_id=doc_id,
                source_title=source_title,
                source_url=source_url_or_path,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section=chunk.section,
                extractor=f"groq/{self.model}",
                confidence=float(rc.get("confidence", 0.9)),
            )

            concept = OKFConcept(
                id=c_id,
                name=c_name,
                category=rc.get("category", "Entity"),
                definition=rc.get("definition", f"Concept extracted from {source_title}"),
                aliases=rc.get("aliases", []),
                provenance=prov,
                relationships=[],
                mention_count=1,
                tags=[rc.get("category", "Entity")],
            )
            concepts.append(concept)
            chunk.concepts.append(c_name)

        for r_idx, rr in enumerate(raw_rels):
            src = rr.get("source", "").strip().title()
            tgt = rr.get("target", "").strip().title()
            rtype = rr.get("relation_type", "USES").strip().upper()

            if src and tgt and src != tgt:
                rel = OKFRelationship(
                    id=f"rel_{uuid.uuid4().hex[:8]}",
                    source=src,
                    target=tgt,
                    relation_type=rtype,
                    description=rr.get("description", f"{src} {rtype.lower()} {tgt}"),
                    evidence_quote=rr.get("evidence_quote", ""),
                    doc_id=doc_id,
                    chunk_id=chunk.chunk_id,
                    confidence=0.9,
                )
                relationships.append(rel)

        return concepts, relationships

    def _extract_with_heuristics(
        self,
        chunk: DocumentChunk,
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Heuristic rule-based NLP extraction when Groq API key is not yet set."""
        text = chunk.cleaned_content
        concepts: List[OKFConcept] = []
        relationships: List[OKFRelationship] = []

        # Find capitalized technical terms or phrases
        # Matches Title Case phrases like "Vector Index", "Attention Mechanism", "MongoDB", "RAG Pipeline"
        pattern = r'\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,3})\b'
        candidates = re.findall(pattern, text)

        # Filter stopwords
        stopwords = {
            "The", "This", "That", "These", "Those", "When", "Where", "What", "Which", "Why",
            "How", "In", "On", "At", "For", "With", "Without", "From", "To", "By", "An", "A",
            "It", "We", "They", "Our", "Their", "However", "Furthermore", "Moreover", "Although"
        }

        term_freq = {}
        for c in candidates:
            c_clean = c.strip()
            if c_clean not in stopwords and len(c_clean) > 3 and not c_clean.isdigit():
                term_freq[c_clean] = term_freq.get(c_clean, 0) + 1

        top_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)[:6]

        extracted_concept_names = []
        for term, freq in top_terms:
            c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', term.lower())[:32]}"
            
            # Simple category deduction
            category = "Entity"
            term_l = term.lower()
            if any(w in term_l for w in ["model", "network", "transformer", "architecture", "system", "engine"]):
                category = "Architecture"
            elif any(w in term_l for w in ["mechanism", "attention", "retrieval", "search", "algorithm"]):
                category = "Mechanism"
            elif any(w in term_l for w in ["database", "tool", "mongo", "chroma", "langchain", "groq", "loader"]):
                category = "Tool"
            elif any(w in term_l for w in ["score", "metric", "accuracy", "loss", "recall"]):
                category = "Metric"
            elif any(w in term_l for w in ["format", "protocol", "yaml", "json", "api", "okf"]):
                category = "Protocol"

            # Look for sentence containing this term for definition
            definition = f"A key {category.lower()} identified in {source_title}."
            for sent in re.split(r'(?<=[.!?])\s+', text):
                if term in sent and len(sent) > 20:
                    definition = sent.strip()
                    break

            prov = OKFProvenance(
                source_id=doc_id,
                source_title=source_title,
                source_url=source_url_or_path,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section=chunk.section,
                extractor="heuristic/rule-based-nlp",
                confidence=0.82,
            )

            concept = OKFConcept(
                id=c_id,
                name=term,
                category=category,
                definition=definition,
                aliases=[],
                provenance=prov,
                relationships=[],
                mention_count=freq,
                tags=[category],
            )
            concepts.append(concept)
            extracted_concept_names.append(term)
            chunk.concepts.append(term)

        # Form heuristic relationships between co-occurring concepts in the same sentence
        for i in range(len(extracted_concept_names)):
            for j in range(i + 1, min(i + 3, len(extracted_concept_names))):
                c1 = extracted_concept_names[i]
                c2 = extracted_concept_names[j]

                # Check if they occur in the same sentence
                for sent in re.split(r'(?<=[.!?])\s+', text):
                    if c1 in sent and c2 in sent:
                        rel_type = "USES"
                        sent_l = sent.lower()
                        if "implements" in sent_l or "built" in sent_l:
                            rel_type = "IMPLEMENTS"
                        elif "part of" in sent_l or "contains" in sent_l or "consists" in sent_l:
                            rel_type = "PART_OF"
                        elif "enables" in sent_l or "allows" in sent_l or "improves" in sent_l:
                            rel_type = "ENABLES"
                        elif "extends" in sent_l or "replaces" in sent_l:
                            rel_type = "EXTENDS"

                        relationships.append(
                            OKFRelationship(
                                id=f"rel_{uuid.uuid4().hex[:8]}",
                                source=c1,
                                target=c2,
                                relation_type=rel_type,
                                description=f"{c1} {rel_type.lower()} {c2} according to document context.",
                                evidence_quote=sent.strip(),
                                doc_id=doc_id,
                                chunk_id=chunk.chunk_id,
                                confidence=0.8,
                            )
                        )
                        break

        return concepts, relationships
