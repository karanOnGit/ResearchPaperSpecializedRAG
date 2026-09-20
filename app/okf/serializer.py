import yaml
from typing import Dict, Any, List, Optional
from app.okf.models import OKFConcept, OKFRelationship, OKFSource, OKFDocumentBundle, OKFProvenance

class OKFSerializer:
    """Serializes and deserializes OKF objects to/from Markdown + YAML."""

    @staticmethod
    def concept_to_markdown_yaml(concept: OKFConcept) -> str:
        """Serialize an OKFConcept to a Markdown document with YAML frontmatter."""
        frontmatter_data = {
            "okf_version": "1.0",
            "type": "concept",
            "id": concept.id,
            "name": concept.name,
            "category": concept.category,
            "aliases": concept.aliases,
            "provenance": {
                "source_id": concept.provenance.source_id,
                "source_title": concept.provenance.source_title,
                "source_url": concept.provenance.source_url,
                "chunk_id": concept.provenance.chunk_id,
                "page_number": concept.provenance.page_number,
                "section": concept.provenance.section,
                "extracted_at": concept.provenance.extracted_at,
                "extractor": concept.provenance.extractor,
                "confidence": concept.provenance.confidence,
            },
            "relationships": [
                {
                    "target": r.target,
                    "relation_type": r.relation_type,
                    "description": r.description,
                    "confidence": r.confidence,
                }
                for r in concept.relationships
            ],
            "tags": concept.tags,
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
            "",
            "## Relationships",
        ]

        if concept.relationships:
            for r in concept.relationships:
                body_lines.append(f"- **{concept.name}** `[{r.relation_type}]` **{r.target}**")
                if r.description:
                    body_lines.append(f"  - *Description*: {r.description}")
                if r.evidence_quote:
                    body_lines.append(f"  - *Evidence*: > \"{r.evidence_quote}\"")
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
