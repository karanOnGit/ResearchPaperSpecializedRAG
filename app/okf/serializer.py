import re
import yaml
from typing import Dict, Any, List, Optional
from app.okf.models import OKFConcept, OKFRelationship, OKFSource, OKFDocumentBundle, OKFProvenance

class OKFSerializer:
    """Serializes and deserializes OKF objects to/from Markdown + YAML."""

    @staticmethod
    def _to_concept_id(target_name: str) -> str:
        """Convert a target name into a clean concept ID."""
        if target_name.startswith("concept_"):
            return target_name
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', target_name.lower()).strip('_')
        return f"concept_{slug[:32]}"

    @classmethod
    def concept_to_markdown_yaml(cls, concept: OKFConcept) -> str:
        """Serialize an OKFConcept to a Markdown document with YAML frontmatter."""
        prov_dict = {
            "source_id": concept.provenance.source_id,
            "source_title": concept.provenance.source_title,
            "source_url": concept.provenance.source_url,
            "chunk_id": concept.provenance.chunk_id,
        }
        if concept.provenance.page_number is not None:
            prov_dict["page_number"] = concept.provenance.page_number
        if concept.provenance.section:
            prov_dict["section"] = concept.provenance.section
        prov_dict["extracted_at"] = concept.provenance.extracted_at
        prov_dict["extractor"] = concept.provenance.extractor
        prov_dict["confidence"] = round(float(concept.provenance.confidence), 2)

        # Build clean frontmatter relationships: type + target concept ID
        frontmatter_rels = []
        seen_pairs = set()
        for r in concept.relationships:
            tgt_id = cls._to_concept_id(r.target)
            pair_key = (r.relation_type, tgt_id)
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                frontmatter_rels.append({
                    "type": r.relation_type,
                    "target": tgt_id,
                })

        frontmatter_data = {
            "okf_version": "1.0",
            "type": "concept",
            "id": concept.id,
            "name": concept.name,
            "category": concept.category,
            "aliases": concept.aliases,
            "provenance": prov_dict,
            "relationships": frontmatter_rels,
            "tags": concept.tags if concept.tags else [concept.category],
            "mention_count": concept.mention_count,
        }

        yaml_str = yaml.dump(frontmatter_data, sort_keys=False, default_flow_style=False)

        body_lines = [
            f"# {concept.name}",
            "",
            f"**Category**: `{concept.category}`  ",
            f"**Confidence**: `{concept.provenance.confidence:.2f}`  ",
            f"**Source**: [{concept.provenance.source_title}]({concept.provenance.source_url})",
            "",
            "## Definition",
            concept.definition,
        ]

        # Key Components section (if present)
        if hasattr(concept, "components") and concept.components:
            body_lines.extend(["", "## Key Components"])
            for comp_name, comp_desc in concept.components.items():
                body_lines.append(f"- **{comp_name}**: {comp_desc}")

        # Relationships section
        body_lines.extend(["", "## Relationships"])
        if concept.relationships:
            # Group hasType and multi-target relations
            grouped_rels: Dict[str, List[str]] = {}
            for r in concept.relationships:
                grouped_rels.setdefault(r.relation_type, []).append(r.target)

            for rtype, targets in grouped_rels.items():
                # Deduplicate targets maintaining order
                unique_tgts = []
                for t in targets:
                    if t not in unique_tgts:
                        unique_tgts.append(t)

                if rtype in ["hasType", "subtypes", "TYPES"] or len(unique_tgts) > 4:
                    body_lines.append(f"- {rtype} → {', '.join(unique_tgts)}")
                else:
                    for t in unique_tgts:
                        body_lines.append(f"- {rtype} → {t}")
        else:
            body_lines.append("*No direct relationships recorded yet.*")

        if concept.aliases:
            body_lines.extend(["", "## Known Aliases", ", ".join(f"`{a}`" for a in concept.aliases)])

        return f"---\n{yaml_str}---\n\n" + "\n".join(body_lines)

    @staticmethod
    def source_to_markdown_yaml(source: OKFSource, concepts: List[OKFConcept] = None, relationships: List[OKFRelationship] = None) -> str:
        """Serialize an OKFSource and its knowledge graph to Markdown + YAML."""
        concepts = concepts or []
        relationships = relationships or []

        frontmatter_data = {
            "okf_version": "1.0",
            "type": "document_source",
            "id": source.id,
            "title": source.title,
            "source_type": source.source_type,
            "source_path_or_url": source.source_path_or_url,
            "author": source.author,
            "published_date": source.published_date,
            "created_at": source.created_at,
            "total_chunks": source.total_chunks,
            "total_concepts": len(concepts),
            "total_relationships": len(relationships),
            "concepts_extracted": [c.name for c in concepts],
        }

        yaml_str = yaml.dump(frontmatter_data, sort_keys=False, default_flow_style=False)

        body_lines = [
            f"# {source.title}",
            "",
            f"**Source Type**: `{source.source_type.upper()}`  ",
            f"**Location**: `{source.source_path_or_url}`  ",
            f"**Ingested At**: `{source.created_at}`  ",
            f"**Total Chunks**: `{source.total_chunks}`  ",
            f"**Total Concepts Extracted**: `{len(concepts)}`  ",
            "",
            "## Summary",
            source.summary if source.summary else "*No automated summary generated yet.*",
            "",
            "## Extracted Typed Concepts",
        ]

        if concepts:
            for c in concepts:
                body_lines.append(f"### {c.name} (`{c.category}`)")
                body_lines.append(f"> {c.definition}")
                body_lines.append("")
        else:
            body_lines.append("*No concepts extracted from this source yet.*")

        body_lines.extend(["", "## Extracted Relationships"])
        if relationships:
            for r in relationships:
                body_lines.append(f"- **{r.source}** `{r.relation_type}` **{r.target}**")
                if r.description:
                    body_lines.append(f"  - {r.description}")
        else:
            body_lines.append("*No relationships extracted.*")

        return f"---\n{yaml_str}---\n\n" + "\n".join(body_lines)

    @staticmethod
    def parse_markdown_yaml(content: str) -> Dict[str, Any]:
        """Parse a Markdown + YAML frontmatter string."""
        if not content.startswith("---"):
            return {"body": content, "frontmatter": {}}
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_raw = parts[1]
            body = parts[2].strip()
            data = yaml.safe_load(frontmatter_raw) or {}
            return {"frontmatter": data, "body": body}
        return {"body": content, "frontmatter": {}}
