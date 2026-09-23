import json
import re
import uuid
from typing import List, Dict, Any, Tuple
from app.config import config
from app.okf.models import OKFConcept, OKFRelationship, OKFProvenance, DocumentChunk
from app.storage.mongo_manager import MongoManager

class GroqKnowledgeExtractor:
    """Knowledge extraction engine using Groq LLM (with heuristic NLP fallback)."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.groq_api_key
        self.model = model or config.extraction_model

    # ==================== High-Level Extraction ====================

    def extract_from_chunks(
        self,
        chunks: List[DocumentChunk],
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Extract typed concepts, structured components, taxonomies, and relationships across document chunks."""
        all_concepts: Dict[str, OKFConcept] = {}
        all_relationships: List[OKFRelationship] = []

        # 0. Extract explicit relationship triples and structured definitions from markdown/text chunks
        explicit_concepts, explicit_rels = self._extract_explicit_triples_and_headings(
            chunks=chunks,
            doc_id=doc_id,
            source_title=source_title,
            source_url_or_path=source_url_or_path
        )
        for ec in explicit_concepts:
            all_concepts[ec.name] = ec
        all_relationships.extend(explicit_rels)

        # Process key representative chunks with Groq (up to 2 chunks to stay within OTPM limits)
        # and supplement remaining chunks with heuristic extraction
        groq_chunks_limit = 2
        groq_chunks_processed = 0

        for idx, chunk in enumerate(chunks):
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
                    for a in c.aliases:
                        if a not in existing.aliases:
                            existing.aliases.append(a)
                    for t in c.tags:
                        if t not in existing.tags:
                            existing.tags.append(t)
                    if hasattr(c, "components") and c.components:
                        existing.components.update(c.components)

                    # Update definition and provenance if the new candidate is superior
                    if MongoManager._is_better_definition(c.definition, existing.definition):
                        existing.definition = c.definition
                        existing.provenance = c.provenance
                        if c.category != "Entity":
                            existing.category = c.category
                else:
                    c.name = norm_name
                    all_concepts[norm_name] = c

            all_relationships.extend(relationships)

        # 2. Extract structured components and taxonomy relationships (hasComponent, hasType)
        comp_concepts, comp_rels = self._extract_components_and_taxonomies(
            chunks=chunks,
            doc_id=doc_id,
            source_title=source_title,
            source_url_or_path=source_url_or_path,
            existing_concepts=all_concepts
        )
        for cc in comp_concepts:
            norm_name = cc.name.strip().title()
            if norm_name in all_concepts:
                existing = all_concepts[norm_name]
                existing.mention_count += 1
                for a in cc.aliases:
                    if a not in existing.aliases:
                        existing.aliases.append(a)
                for t in cc.tags:
                    if t not in existing.tags:
                        existing.tags.append(t)
                if hasattr(cc, "components") and cc.components:
                    existing.components.update(cc.components)
                if MongoManager._is_better_definition(cc.definition, existing.definition):
                    existing.definition = cc.definition
                    existing.provenance = cc.provenance
                    if cc.category != "Entity":
                        existing.category = cc.category
            else:
                cc.name = norm_name
                all_concepts[norm_name] = cc

        all_relationships.extend(comp_rels)

        # De-duplicate relationships
        unique_rels: List[OKFRelationship] = []
        rel_signatures = set()
        for r in all_relationships:
            sig = (r.source.strip().title(), r.relation_type.strip(), r.target.strip().title())
            if sig not in rel_signatures:
                rel_signatures.add(sig)
                unique_rels.append(r)

        # Attach outgoing relationships directly to each concept
        for c in all_concepts.values():
            c_name_l = c.name.strip().lower()
            matching_rels = [
                r for r in unique_rels
                if r.source.strip().lower() == c_name_l
            ]
            seen_c_rels = set()
            c.relationships = []
            for r in matching_rels:
                sig = (r.relation_type, r.target.strip().lower())
                if sig not in seen_c_rels:
                    seen_c_rels.add(sig)
                    c.relationships.append(r)

        return list(all_concepts.values()), unique_rels

    # ==================== Chunk-Level Dispatchers ====================

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
1. Concept Categories: Psychological Construct, Neurochemical, Neural Substrate, Theory, Architecture, Mechanism, Tool, Metric, Protocol, Entity.
2. Concept Definition: Factual, authoritative 1-2 sentence technical definition. NEVER use markdown table rows, bullet points, or syntax.
3. Components: If the concept has defined components or dimensions (e.g., Sternberg's intimacy, passion, commitment), include them in "components": {{"ComponentName": "Description"}}.
4. Relationships: Use standard relation types:
   - hasComponent: e.g. Love -> Intimacy
   - hasType: e.g. Love -> Romantic Love
   - IMPLEMENTS, USES, EXTENDS, EVALUATED_ON, ENABLES, CAUSES, PART_OF, CONTRADICTS.
5. Quote: Include exact short verbatim quote from the text supporting each relationship.

Text Chunk:
\"\"\"{chunk.cleaned_content}\"\"\"

Return ONLY valid JSON matching this schema:
{{
  "concepts": [
    {{
      "name": "Concept Name",
      "category": "Psychological Construct|Theory|Architecture|Mechanism|Neurochemical|Tool|Metric",
      "definition": "Clear authoritative prose definition.",
      "aliases": ["Alternative Name"],
      "components": {{"Component": "Description"}},
      "tags": ["Category", "Author", "Domain"],
      "confidence": 0.95
    }}
  ],
  "relationships": [
    {{
      "source": "Concept A",
      "target": "Concept B",
      "relation_type": "hasComponent|hasType|USES|IMPLEMENTS|PART_OF|ENABLES",
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
            max_tokens=2048,
        )

        content = response.choices[0].message.content or ""
        clean_content = content.strip()
        if clean_content.startswith("```"):
            clean_content = re.sub(r"^```(?:json)?\s*", "", clean_content)
            clean_content = re.sub(r"\s*```$", "", clean_content)

        if not clean_content or not clean_content.startswith("{"):
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
            category = rc.get("category") or self._infer_concept_category(c_name, chunk.cleaned_content)
            tags = rc.get("tags") or self._infer_tags(c_name, category, chunk.cleaned_content)
            components = rc.get("components", {})

            prov = OKFProvenance(
                source_id=doc_id,
                source_title=source_title,
                source_url=source_url_or_path,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section=chunk.section,
                extractor=f"groq/{self.model}",
                confidence=float(rc.get("confidence", 0.95)),
            )

            concept = OKFConcept(
                id=c_id,
                name=c_name,
                category=category,
                definition=rc.get("definition", f"Concept extracted from {source_title}"),
                aliases=rc.get("aliases", []),
                provenance=prov,
                components=components if isinstance(components, dict) else {},
                relationships=[],
                mention_count=1,
                tags=tags if isinstance(tags, list) else [category],
            )
            concepts.append(concept)
            chunk.concepts.append(c_name)

        for r_idx, rr in enumerate(raw_rels):
            src = rr.get("source", "").strip().title()
            tgt = rr.get("target", "").strip().title()
            rtype = rr.get("relation_type", "USES").strip()

            if src and tgt and src != tgt:
                rel = OKFRelationship(
                    id=f"rel_{uuid.uuid4().hex[:8]}",
                    source=src,
                    target=tgt,
                    relation_type=rtype,
                    description=rr.get("description", f"{src} {rtype} {tgt}"),
                    evidence_quote=rr.get("evidence_quote", ""),
                    doc_id=doc_id,
                    chunk_id=chunk.chunk_id,
                    confidence=0.92,
                )
                relationships.append(rel)

        return concepts, relationships

    # ==================== Heuristic Extraction & Scoring ====================

    @staticmethod
    def _score_definition_candidate(sent: str, term: str, section: str = "") -> float:
        """Score how well a sentence serves as an authoritative definition for a concept."""
        if not sent or not sent.strip():
            return -1000.0

        sent_s = sent.strip()

        # Immediate disqualifiers: markdown tables, raw headers, code blocks
        if "|" in sent_s or "|---" in sent_s or sent_s.startswith("#") or sent_s.startswith("```"):
            return -1000.0

        # Term must be in sentence
        term_pattern = r'\b' + re.escape(term.lower()) + r'\b'
        if not re.search(term_pattern, sent_s.lower()):
            return -500.0

        score = 10.0
        sent_l = sent_s.lower()
        term_l = term.lower()

        # Length evaluation
        length = len(sent_s)
        if length < 35:
            score -= 20.0
        elif 70 <= length <= 350:
            score += 25.0
        elif 351 <= length <= 550:
            score += 15.0
        elif length > 650:
            score -= 15.0

        # Disqualify if it's purely a short list item without prose
        if sent_s.startswith("- **") and ":" in sent_s and length < 60:
            score -= 15.0

        # High-value definitional verbs and constructs
        strong_markers = [
            "consists of", "is defined as", "refers to", "characterized by",
            "composed of", "conceptualized as", "represents", "interconnected components",
            "form the vertices", "essential vertices", "three components",
            "triangular theory", "tripartite model", "governed by", "primary mediators",
            "is a geometric construct", "operates through", "framework"
        ]
        for marker in strong_markers:
            if marker in sent_l:
                score += 35.0
                break

        medium_markers = [
            "involves", "includes", "identifies", "describes", "structure",
            "mechanism", "functions as", "serves to", "relies on", "manifests as"
        ]
        for marker in medium_markers:
            if marker in sent_l:
                score += 15.0
                break

        # Author or citation markers indicate academic authority
        citation_markers = [
            "according to", "conceptualized", "developed by", "categorizes",
            "theorized", "(1986)", "(1990)", "(20", "(19"
        ]
        for cm in citation_markers:
            if cm in sent_l:
                score += 20.0
                break

        # Term prominence (appearing in first 50 chars of the sentence)
        first_50 = sent_l[:50]
        if term_l in first_50:
            score += 20.0

        # Section relevance
        if section:
            sec_l = section.lower()
            if term_l in sec_l:
                score += 15.0
            if any(k in sec_l for k in ["overview", "foundations", "theory", "definition", "introduction", "three components"]):
                score += 15.0
            if any(k in sec_l for k in ["types", "table", "appendix", "interaction taxonomy"]):
                score -= 20.0

        return score

    def _find_best_definition(
        self,
        text: str,
        term: str,
        section: str = "",
        source_title: str = "",
        category: str = "Entity"
    ) -> Tuple[str, float]:
        """Find the most authoritative definition sentence from text for term."""
        # Clean markdown tables and noisy lines
        clean_lines = []
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("|") or "|---" in line_s or line_s.endswith("|"):
                continue
            if line_s.startswith("#"):
                continue
            clean_lines.append(line)
        cleaned_text = "\n".join(clean_lines)

        sentence_splits = re.split(r'(?<=[.!?])\s+|\n\n+', cleaned_text)

        best_sent = f"A key {category.lower()} identified in {source_title}."
        best_score = -999.0

        for sent in sentence_splits:
            sent_s = sent.strip()
            if not sent_s:
                continue
            sent_clean = re.sub(r'^[0-9]+[\.\)]\s*', '', sent_s)
            sent_clean = re.sub(r'^[\-\*]\s*', '', sent_clean)

            score = self._score_definition_candidate(sent_clean, term, section)
            if score > best_score:
                best_score = score
                best_sent = sent_clean

        if best_score >= 40.0:
            confidence = min(0.95, 0.85 + (best_score / 400.0))
        elif best_score > 0.0:
            confidence = 0.82
        else:
            confidence = 0.75

        return best_sent, round(confidence, 2)

    @staticmethod
    def _infer_concept_category(term: str, context: str = "") -> str:
        """Infer accurate domain category for a concept."""
        term_l = term.lower()
        ctx_l = context.lower()
        combined = f"{term_l} {ctx_l}"

        psych_keywords = [
            "love", "intimacy", "passion", "commitment", "attachment",
            "infatuation", "desire", "libido", "craving", "arousal",
            "emotion", "construct", "affective", "psychological",
            "temperament", "vulnerability", "self-esteem", "cognition",
            "nonlove", "companionate", "consummate", "fatuous"
        ]
        if any(w in term_l for w in psych_keywords):
            return "Psychological Construct"

        neuro_keywords = [
            "dopamine", "serotonin", "oxytocin", "vasopressin", "endorphin",
            "testosterone", "estrogen", "androgen", "dhea", "hormone",
            "neurotransmitter", "ngf", "norepinephrine"
        ]
        if any(w in term_l for w in neuro_keywords):
            return "Neurochemical"

        brain_keywords = [
            "hypothalamus", "amygdala", "vta", "nucleus accumbens",
            "cortex", "septum", "mpoa", "bnst", "pvn", "cingulate",
            "prefrontal"
        ]
        if any(w in term_l for w in brain_keywords):
            return "Neural Substrate"

        arch_keywords = ["model", "network", "transformer", "architecture", "system", "engine", "pipeline"]
        if any(w in term_l for w in arch_keywords):
            return "Architecture"

        mech_keywords = ["mechanism", "attention", "retrieval", "search", "algorithm", "inhibition", "excitation"]
        if any(w in term_l for w in mech_keywords):
            return "Mechanism"

        tool_keywords = ["database", "tool", "mongo", "chroma", "langchain", "groq", "loader", "pymupdf"]
        if any(w in term_l for w in tool_keywords):
            return "Tool"

        metric_keywords = ["score", "metric", "accuracy", "loss", "recall", "precision", "f1"]
        if any(w in term_l for w in metric_keywords):
            return "Metric"

        proto_keywords = ["format", "protocol", "yaml", "json", "api", "okf", "http"]
        if any(w in term_l for w in proto_keywords):
            return "Protocol"

        theory_keywords = ["theory", "framework", "taxonomy", "paradigm", "hypothesis", "crucible approach"]
        if any(w in term_l for w in theory_keywords):
            return "Theory"

        if any(w in combined for w in ["psychological construct", "triangular theory of love", "pair-bonding"]):
            return "Psychological Construct"

        return "Entity"

    @staticmethod
    def _infer_tags(term: str, category: str, text: str = "") -> List[str]:
        """Generate meaningful tags for a concept."""
        tags = [category] if category != "Entity" else []
        text_l = text.lower()
        term_l = term.lower()

        if "sternberg" in text_l or "sternberg" in term_l:
            tags.append("Sternberg")
        if "fisher" in text_l:
            tags.append("Helen Fisher")
        if "bowlby" in text_l or "ainsworth" in text_l:
            tags.append("Attachment Theory")
        if "perel" in text_l:
            tags.append("Esther Perel")
        if "schnarch" in text_l:
            tags.append("David Schnarch")
        if "vaswani" in text_l or "transformer" in text_l:
            tags.append("Transformers")

        if "love" in term_l or "triangular" in text_l:
            tags.append("Love Theory")
        elif "attachment" in term_l:
            tags.append("Attachment Theory")
        elif category in ["Neurochemical", "Neural Substrate"]:
            tags.append("Neurobiology")

        if not tags:
            tags = [category]

        unique_tags = []
        for t in tags:
            if t not in unique_tags:
                unique_tags.append(t)
        return unique_tags

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

        pattern = r'\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,3})\b'
        candidates = re.findall(pattern, text)

        stopwords = {
            "The", "This", "That", "These", "Those", "When", "Where", "What", "Which", "Why",
            "How", "In", "On", "At", "For", "With", "Without", "From", "To", "By", "An", "A",
            "It", "We", "They", "Our", "Their", "However", "Furthermore", "Moreover", "Although",
            "Only", "After", "Before", "Because", "Instead", "During", "Since", "Until",
            "Type", "Definition", "Function", "Attributes", "Overview", "Source", "Version", "Created",
            "Key Passages", "Provenance", "Summary", "Significance", "Manifestations", "Setting",
            "Sphere", "Narrative", "Narrative Summary", "Daytime", "Satisfaction", "Present", "Power",
            "Final", "Entities", "Concepts", "Core Concepts", "Primary Concept", "Key Actions",
            "Desire Relationships", "Temporal Relationships", "Linguistic Relationships", "Recognition Relationships",
            "Removes", "Performs", "Acknowledges", "Receives", "Allows", "Transforms", "Names"
        }

        term_freq = {}
        for c in candidates:
            c_clean = c.strip().title()
            if c_clean not in stopwords and len(c_clean) > 2 and not c_clean.isdigit():
                term_freq[c_clean] = term_freq.get(c_clean, 0) + 1

        # Also detect core concepts from the section name or title
        sec_name = chunk.section or ""
        for term_cand in ["Love", "Intimacy", "Passion", "Commitment", "Lust", "Attraction", "Attachment", "Attention"]:
            if term_cand.lower() in text.lower() or term_cand.lower() in sec_name.lower():
                term_freq[term_cand] = term_freq.get(term_cand, 0) + 3

        top_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)[:8]

        extracted_concept_names = []
        for term, freq in top_terms:
            c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', term.lower())[:32]}"
            category = self._infer_concept_category(term, text)
            tags = self._infer_tags(term, category, text)

            # Smart definition extraction using scoring function
            definition, conf = self._find_best_definition(
                text=text,
                term=term,
                section=chunk.section or "",
                source_title=source_title,
                category=category
            )

            # Formulate aliases
            aliases = []
            if term.lower() == "love":
                aliases = ["Romantic Love", "Triangular Love"]

            prov = OKFProvenance(
                source_id=doc_id,
                source_title=source_title,
                source_url=source_url_or_path,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section=chunk.section,
                extractor="heuristic/rule-based-nlp",
                confidence=conf,
            )

            concept = OKFConcept(
                id=c_id,
                name=term,
                category=category,
                definition=definition,
                aliases=aliases,
                provenance=prov,
                components={},
                relationships=[],
                mention_count=freq,
                tags=tags,
            )
            concepts.append(concept)
            extracted_concept_names.append(term)
            chunk.concepts.append(term)

        # Form heuristic relationships between co-occurring concepts
        clean_lines = [l for l in text.splitlines() if not l.strip().startswith("|")]
        for i in range(len(extracted_concept_names)):
            for j in range(i + 1, min(i + 3, len(extracted_concept_names))):
                c1 = extracted_concept_names[i]
                c2 = extracted_concept_names[j]

                for line in clean_lines:
                    if c1 in line and c2 in line and len(line) > 20:
                        rel_type = "USES"
                        line_l = line.lower()
                        if "implements" in line_l or "built" in line_l:
                            rel_type = "IMPLEMENTS"
                        elif "part of" in line_l or "contains" in line_l or "consists" in line_l:
                            rel_type = "PART_OF"
                        elif "enables" in line_l or "allows" in line_l or "improves" in line_l:
                            rel_type = "ENABLES"
                        elif "extends" in line_l or "replaces" in line_l:
                            rel_type = "EXTENDS"

                        relationships.append(
                            OKFRelationship(
                                id=f"rel_{uuid.uuid4().hex[:8]}",
                                source=c1,
                                target=c2,
                                relation_type=rel_type,
                                description=f"{c1} {rel_type.lower()} {c2} according to document context.",
                                evidence_quote=line.strip(),
                                doc_id=doc_id,
                                chunk_id=chunk.chunk_id,
                                confidence=0.82,
                            )
                        )
                        break

        return concepts, relationships

    # ==================== Component & Taxonomy Parser ====================

    def _extract_components_and_taxonomies(
        self,
        chunks: List[DocumentChunk],
        doc_id: str,
        source_title: str,
        source_url_or_path: str,
        existing_concepts: Dict[str, OKFConcept]
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Extract structured components and taxonomy types from tables and component lists."""
        concepts: List[OKFConcept] = []
        relationships: List[OKFRelationship] = []

        title_core = None
        for cand in ["Love", "Romantic Love", "Attention Mechanism", "Transformer", "Pair-Bonding"]:
            if cand.lower() in source_title.lower():
                title_core = cand.title()
                break

        for chunk in chunks:
            text = chunk.cleaned_content
            lines = text.splitlines()
            section = (chunk.section or "").strip()

            parent_concept_name = title_core or "Love"
            if "love" in section.lower() or "sternberg" in section.lower():
                parent_concept_name = "Love"
            elif "lust" in section.lower() or "libido" in section.lower():
                parent_concept_name = "Lust"
            elif "attraction" in section.lower():
                parent_concept_name = "Attraction"
            elif "attachment" in section.lower():
                parent_concept_name = "Attachment"
            elif "sexual excitation" in section.lower() or "ses" in section.lower():
                parent_concept_name = "Sexual Excitation System (SES)"
            elif "sexual inhibition" in section.lower() or "sis" in section.lower():
                parent_concept_name = "Sexual Inhibition System (SIS)"

            # 1. Parse Component Lists (e.g. 1. **Intimacy**: ... or - **Intimacy**: ...)
            comp_pattern = re.compile(r'^[ \t]*(?:\d+[\.\)]|[-*])\s*\*\*([^\*:]+)\*\*:\s*([^\n]+)$')
            chunk_components: Dict[str, str] = {}

            has_component_trigger = any(kw in text.lower() for kw in [
                "components", "vertices", "composed of", "consists of", "three essential",
                "key characteristics", "tripartite", "three distinct", "mediators"
            ]) or "components" in section.lower()

            if has_component_trigger:
                for line in lines:
                    m = comp_pattern.match(line.strip())
                    if m:
                        comp_name = m.group(1).strip()
                        comp_desc = m.group(2).strip()
                        if comp_name.lower() in ["category", "confidence", "source", "author", "type", "dimension", "definition"]:
                            continue
                        if len(comp_name) >= 3 and len(comp_desc) >= 15:
                            comp_clean = comp_name.strip()
                            chunk_components[comp_clean] = comp_desc

                            # Form hasComponent relationship
                            rel = OKFRelationship(
                                id=f"rel_comp_{uuid.uuid4().hex[:8]}",
                                source=parent_concept_name,
                                target=comp_clean,
                                relation_type="hasComponent",
                                description=comp_desc,
                                evidence_quote=line.strip(),
                                doc_id=doc_id,
                                chunk_id=chunk.chunk_id,
                                confidence=0.95
                            )
                            relationships.append(rel)

                            # Create OKFConcept for the component itself
                            c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', comp_clean.lower())[:32]}"
                            cat = self._infer_concept_category(comp_clean, comp_desc)
                            tags = self._infer_tags(comp_clean, cat, text)
                            comp_concept = OKFConcept(
                                id=c_id,
                                name=comp_clean,
                                category=cat,
                                definition=comp_desc,
                                aliases=[],
                                provenance=OKFProvenance(
                                    source_id=doc_id,
                                    source_title=source_title,
                                    source_url=source_url_or_path,
                                    chunk_id=chunk.chunk_id,
                                    page_number=chunk.page_number,
                                    section=chunk.section,
                                    extractor="heuristic/rule-based-nlp",
                                    confidence=0.90
                                ),
                                components={},
                                relationships=[],
                                mention_count=1,
                                tags=tags
                            )
                            concepts.append(comp_concept)

                if chunk_components and parent_concept_name in existing_concepts:
                    existing_concepts[parent_concept_name].components.update(chunk_components)

            # 2. Parse Taxonomy Tables (e.g. ## Eight Types of Love with | Type | Intimacy | ...)
            is_type_table = False
            type_col_idx = None
            table_rows = []

            for line in lines:
                line_s = line.strip()
                if line_s.startswith("|") and line_s.endswith("|"):
                    cells = [c.strip() for c in line_s.strip("|").split("|")]
                    if any("type" in c.lower() for c in cells) and type_col_idx is None:
                        is_type_table = True
                        for idx, c in enumerate(cells):
                            if "type" in c.lower():
                                type_col_idx = idx
                                break
                    elif is_type_table and not all(c.startswith("-") for c in cells if c):
                        if type_col_idx is not None and len(cells) > type_col_idx:
                            table_rows.append((cells[type_col_idx], line_s))

            if is_type_table and table_rows:
                for type_cell, row_line in table_rows:
                    raw_type = type_cell.split("/")[0].strip() if "/" in type_cell else type_cell.strip()
                    raw_type = re.sub(r'[*_`]', '', raw_type).strip()
                    if raw_type and len(raw_type) > 2 and raw_type.lower() not in ["type", "dimension", "name", ""]:
                        rel = OKFRelationship(
                            id=f"rel_type_{uuid.uuid4().hex[:8]}",
                            source=parent_concept_name,
                            target=raw_type,
                            relation_type="hasType",
                            description=f"{raw_type} is a categorized manifestation/type of {parent_concept_name}.",
                            evidence_quote=row_line,
                            doc_id=doc_id,
                            chunk_id=chunk.chunk_id,
                            confidence=0.92
                        )
                        relationships.append(rel)

                        c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', raw_type.lower())[:32]}"
                        cat = self._infer_concept_category(raw_type, row_line)
                        tags = self._infer_tags(raw_type, cat, text)
                        type_concept = OKFConcept(
                            id=c_id,
                            name=raw_type,
                            category=cat,
                            definition=f"A distinct type/variation of {parent_concept_name} identified in {source_title}.",
                            aliases=[],
                            provenance=OKFProvenance(
                                source_id=doc_id,
                                source_title=source_title,
                                source_url=source_url_or_path,
                                chunk_id=chunk.chunk_id,
                                page_number=chunk.page_number,
                                section=chunk.section,
                                extractor="heuristic/rule-based-nlp",
                                confidence=0.88
                            ),
                            components={},
                            relationships=[],
                            mention_count=1,
                            tags=tags
                        )
                        concepts.append(type_concept)

                        if parent_concept_name in existing_concepts:
                            if "love" in raw_type.lower() and raw_type.lower() != "love":
                                if raw_type not in existing_concepts[parent_concept_name].aliases:
                                    existing_concepts[parent_concept_name].aliases.append(raw_type)

            # 3. Parse bulleted taxonomies under "Interaction Taxonomy" or "Types of ..."
            if "taxonomy" in section.lower() or "types of" in section.lower() or "interaction taxonomy" in text.lower():
                for line in lines:
                    m = comp_pattern.match(line.strip())
                    if m:
                        t_name = m.group(1).strip()
                        t_desc = m.group(2).strip()
                        if len(t_name) >= 3 and len(t_desc) >= 10:
                            rel = OKFRelationship(
                                id=f"rel_tax_{uuid.uuid4().hex[:8]}",
                                source=parent_concept_name,
                                target=t_name,
                                relation_type="hasType",
                                description=t_desc,
                                evidence_quote=line.strip(),
                                doc_id=doc_id,
                                chunk_id=chunk.chunk_id,
                                confidence=0.94
                            )
                            relationships.append(rel)

                            if parent_concept_name in existing_concepts:
                                if "love" in t_name.lower() and t_name.lower() != "love":
                                    if t_name not in existing_concepts[parent_concept_name].aliases:
                                        existing_concepts[parent_concept_name].aliases.append(t_name)

        return concepts, relationships

    # ==================== Explicit Arrow & Markdown Parsing ====================

    def _extract_explicit_triples_and_headings(
        self,
        chunks: List[DocumentChunk],
        doc_id: str,
        source_title: str,
        source_url_or_path: str
    ) -> Tuple[List[OKFConcept], List[OKFRelationship]]:
        """Parse explicit relationship arrows, action lists, and structured concept definitions directly from document text."""
        concepts: Dict[str, OKFConcept] = {}
        relationships: List[OKFRelationship] = []

        arrow_pattern = re.compile(
            r'^[ \t]*[-*]\s*([^\*\n]+?)\s*\*\*([^\*\n]+)\*\*\s*(?:→|->)\s*([^\n]+)$',
            re.MULTILINE
        )

        bold_pred_pattern = re.compile(
            r'^[ \t]*[-*]\s*([^\*\n]+?)\s*\*\*([^\*\n]+)\*\*\s+([^\n]+)$',
            re.MULTILINE
        )

        for chunk in chunks:
            text = chunk.cleaned_content
            lines = text.splitlines()

            # 1. Parse Arrow Relationships
            for match in arrow_pattern.finditer(text):
                src_raw = match.group(1).strip().strip('"\'')
                pred_raw = match.group(2).strip()
                tgt_raw = match.group(3).strip().strip('"\'')

                if src_raw and tgt_raw and len(src_raw) > 1 and len(tgt_raw) > 1:
                    src_clean = src_raw.strip().title()
                    tgt_clean = tgt_raw.strip().title()
                    pred_clean = re.sub(r'\s+', '_', pred_raw.strip().upper())
                    evidence = match.group(0).strip()
                    desc = f"{src_raw} {pred_raw} {tgt_raw}"

                    rel_id = f"rel_exp_{uuid.uuid4().hex[:8]}"
                    rel = OKFRelationship(
                        id=rel_id,
                        source=src_clean,
                        target=tgt_clean,
                        relation_type=pred_clean,
                        description=desc,
                        evidence_quote=evidence,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        confidence=1.0,
                    )
                    relationships.append(rel)

                    for ep_name in [src_clean, tgt_clean]:
                        if ep_name not in concepts and len(ep_name) > 2:
                            c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', ep_name.lower())[:32]}"
                            cat = self._infer_concept_category(ep_name, evidence)
                            tags = self._infer_tags(ep_name, cat, text)
                            concepts[ep_name] = OKFConcept(
                                id=c_id,
                                name=ep_name,
                                category=cat,
                                definition=f"Explicit knowledge graph node identified in {source_title}.",
                                aliases=[],
                                provenance=OKFProvenance(
                                    source_id=doc_id,
                                    source_title=source_title,
                                    source_url=source_url_or_path,
                                    chunk_id=chunk.chunk_id,
                                    page_number=chunk.page_number,
                                    extractor="explicit/markdown-triple-parser",
                                    confidence=1.0
                                ),
                                components={},
                                relationships=[],
                                mention_count=1,
                                tags=tags
                            )
                            chunk.concepts.append(ep_name)

            # 2. Parse Bold Predicate Relationships
            for match in bold_pred_pattern.finditer(text):
                src_raw = match.group(1).strip().strip('"\'')
                pred_raw = match.group(2).strip()
                tgt_raw = match.group(3).strip().strip('"\'')

                if "→" in tgt_raw or "->" in tgt_raw:
                    continue

                if src_raw and tgt_raw and len(src_raw) > 1 and len(tgt_raw) > 1:
                    src_clean = src_raw.strip().title()
                    tgt_clean = tgt_raw.strip().title()
                    pred_clean = re.sub(r'\s+', '_', pred_raw.strip().upper())
                    evidence = match.group(0).strip()
                    desc = f"{src_raw} {pred_raw} {tgt_raw}"

                    rel_id = f"rel_exp_{uuid.uuid4().hex[:8]}"
                    rel = OKFRelationship(
                        id=rel_id,
                        source=src_clean,
                        target=tgt_clean,
                        relation_type=pred_clean,
                        description=desc,
                        evidence_quote=evidence,
                        doc_id=doc_id,
                        chunk_id=chunk.chunk_id,
                        confidence=0.95,
                    )
                    relationships.append(rel)

            # 3. Parse Character/Entity Key Actions
            current_entity = None
            in_actions_block = False

            for line in lines:
                line_s = line.strip()
                if line_s.startswith("### ") or line_s.startswith("## "):
                    header_name = re.sub(r'^[#]+\s*', '', line_s)
                    header_name = re.sub(r'\s*\(.*?\)', '', header_name).strip()
                    if header_name and len(header_name) > 2 and header_name not in ["Overview", "Key Passages", "Provenance", "Relationships"]:
                        current_entity = header_name.title()
                    else:
                        current_entity = None
                    in_actions_block = False
                    continue

                if current_entity and ("**Key actions**" in line_s or "**Key action" in line_s or "**Key actions:" in line_s):
                    in_actions_block = True
                    continue

                if in_actions_block:
                    if line_s.startswith("- ") or line_s.startswith("* "):
                        action_text = line_s[2:].strip()
                        if action_text:
                            rel_id = f"rel_act_{uuid.uuid4().hex[:8]}"
                            action_target = action_text.title()[:60]
                            rel = OKFRelationship(
                                id=rel_id,
                                source=current_entity,
                                target=action_target,
                                relation_type="PERFORMS_ACTION",
                                description=f"{current_entity} performs action: {action_text}",
                                evidence_quote=line_s,
                                doc_id=doc_id,
                                chunk_id=chunk.chunk_id,
                                confidence=0.95,
                            )
                            relationships.append(rel)
                    elif line_s.startswith("#") or (line_s and not line_s.startswith("-") and not line_s.startswith("*")):
                        in_actions_block = False

            # 4. Parse Structured Concept Definitions (e.g. ### ConceptName (Category) \n - **Definition**: ...)
            concept_header_matches = re.finditer(
                r'###\s+([A-Za-z0-9\s"\'\-]+?)(?:\s*\((?:`?)([A-Za-z0-9\s]+)(?:`?)\))?\s*\n(?:>\s*(.+?)\n|(?:\s*-\s*\*\*Type\*\*:[^\n]+\n)?\s*-\s*\*\*Definition\*\*:\s*([^\n]+))',
                text
            )
            for chm in concept_header_matches:
                c_raw_name = chm.group(1).strip().strip('"\'').title()
                cat_raw = (chm.group(2) or "").strip()
                def_raw = (chm.group(3) or chm.group(4) or "").strip()

                if c_raw_name and len(c_raw_name) > 2 and def_raw and c_raw_name not in ["Key Passages", "Provenance", "Relationships", "Summary"]:
                    c_id = f"concept_{re.sub(r'[^a-zA-Z0-9]', '_', c_raw_name.lower())[:32]}"
                    category = cat_raw.title() if cat_raw else self._infer_concept_category(c_raw_name, def_raw)
                    tags = self._infer_tags(c_raw_name, category, text)
                    concepts[c_raw_name] = OKFConcept(
                        id=c_id,
                        name=c_raw_name,
                        category=category,
                        definition=def_raw,
                        aliases=[],
                        provenance=OKFProvenance(
                            source_id=doc_id,
                            source_title=source_title,
                            source_url=source_url_or_path,
                            chunk_id=chunk.chunk_id,
                            page_number=chunk.page_number,
                            extractor="explicit/markdown-def-parser",
                            confidence=1.0
                        ),
                        components={},
                        relationships=[],
                        mention_count=1,
                        tags=tags
                    )
                    chunk.concepts.append(c_raw_name)

        return list(concepts.values()), relationships
