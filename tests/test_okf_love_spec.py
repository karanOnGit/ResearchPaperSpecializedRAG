import os
import json
from app.engine import ResearchKnowledgeEngine
from app.okf.serializer import OKFSerializer
from app.okf.models import OKFConcept, OKFRelationship

SAMPLE_STERNBERG_TEXT = """# Sternberg’s Triangular Theory of Love

## Overview / The Three Components

According to Robert J. Sternberg’s Triangular Theory of Love (1986), love consists of three interconnected components that form the vertices of a triangle: **intimacy**, **passion**, and **decision/commitment**. The amount and kind of love a person experiences depends on the absolute and relative strength of these three components.

### Key Components
- **Intimacy**: feelings of closeness, connectedness, and bondedness
- **Passion**: drives related to romance, physical attraction, and sexual consummation
- **Decision/Commitment**: the decision to love someone and the commitment to maintain that love

## Eight Types of Love

| Type | Intimacy | Passion | Commitment | Typical Contexts |
|-----------------------|----------|---------|------------|-------------------------------------------|
| Nonlove | No | No | No | Casual acquaintances |
| Liking / Friendship | Yes | No | No | Close friendships |
| Infatuation | No | Yes | No | "Love at first sight", short-lived crush |
| Empty Love | No | No | Yes | Arranged marriages early on, stagnant relationships |
| Romantic Love | Yes | Yes | No | Early passionate dating relationships |
| Companionate Love | Yes | No | Yes | Long-term marriages, deep friendships, family bonds |
| Fatuous Love | No | Yes | Yes | Whirlwind courtships leading to marriage |
| Consummate Love | Yes | Yes | Yes | Ideal "complete" love (difficult to maintain) |
"""

def test_sternberg_love_okf():
    engine = ResearchKnowledgeEngine()
    
    # Ingest text as pasted_text.md
    res = engine.ingest_markdown_or_text(
        content_or_path=SAMPLE_STERNBERG_TEXT,
        is_raw_text=True,
        title="Sternberg’s Triangular Theory of Love"
    )
    assert res["status"] == "success"
    
    # Retrieve concept_love
    c_db = engine.mongo_manager.db.concepts.find_one({"_id": "concept_love"})
    assert c_db is not None, "Concept Love should exist in database"
    
    print("\n--- Concept from Database ---")
    print("Name:", c_db.get("name"))
    print("Category:", c_db.get("category"))
    print("Definition:", c_db.get("definition"))
    print("Components:", c_db.get("components"))
    print("Aliases:", c_db.get("aliases"))
    print("Tags:", c_db.get("tags"))
    print("Provenance chunk_id:", c_db.get("provenance", {}).get("chunk_id"))
    print("Provenance section:", c_db.get("provenance", {}).get("section"))
    print("Provenance confidence:", c_db.get("provenance", {}).get("confidence"))
    
    # 1. Verify Definition does NOT contain markdown table syntax
    assert "|" not in c_db["definition"], "Definition should NOT contain table markdown syntax"
    assert len(c_db["definition"]) > 25, "Definition must be a substantive prose sentence"
    
    # 2. Verify Provenance points to definition chunk/section, NOT the table chunk
    prov = c_db.get("provenance", {})
    assert "c0001" in prov.get("chunk_id", ""), f"Provenance should point to chunk c0001 (Overview), got {prov.get('chunk_id')}"
    assert "Overview" in prov.get("section", "") or "Components" in prov.get("section", ""), "Provenance section should be Overview / Components"
    assert prov.get("confidence", 0) >= 0.85, "Confidence should be high (>= 0.85)"

    # 3. Verify Category
    assert c_db["category"] == "Psychological Construct", f"Category should be Psychological Construct, got {c_db['category']}"
    
    # 4. Verify Components
    assert "Intimacy" in c_db.get("components", {}), "Intimacy component must be present"
    assert "Passion" in c_db.get("components", {}), "Passion component must be present"
    assert "Decision/Commitment" in c_db.get("components", {}), "Decision/Commitment component must be present"
    
    # 5. Test OKF serialization via the endpoint logic
    c_dict = dict(c_db)
    c_dict.pop("_id", None)
    c_obj = OKFConcept(**c_dict)
    
    # Attach relationships from mongo_manager
    graph_rels = engine.mongo_manager.list_relationships_for_concept(c_obj.name)
    existing_sigs = {(r.source.lower(), r.relation_type, r.target.lower()) for r in c_obj.relationships}
    for gr in graph_rels:
        src = gr.get("source", "").strip()
        tgt = gr.get("target", "").strip()
        rtype = gr.get("relation_type", "RELATED_TO").strip()
        if src.lower() == c_obj.name.lower() and tgt:
            sig = (src.lower(), rtype, tgt.lower())
            if sig not in existing_sigs:
                existing_sigs.add(sig)
                c_obj.relationships.append(
                    OKFRelationship(
                        id=str(gr.get("_id") or gr.get("id")),
                        source=src,
                        target=tgt,
                        relation_type=rtype,
                        description=gr.get("description", ""),
                        evidence_quote=gr.get("evidence_quote", ""),
                        confidence=float(gr.get("confidence", 0.9)),
                    )
                )

    md_yaml = OKFSerializer.concept_to_markdown_yaml(c_obj)
    print("\n--- Generated OKF Output ---")
    print(md_yaml)
    
    # 6. Verify OKF YAML Frontmatter and Markdown Body
    assert "okf_version: '1.0'" in md_yaml
    assert "type: concept" in md_yaml
    assert "category: Psychological Construct" in md_yaml
    assert "type: hasComponent" in md_yaml
    assert "target: concept_intimacy" in md_yaml
    assert "type: hasType" in md_yaml
    assert "## Key Components" in md_yaml
    assert "- **Intimacy**:" in md_yaml
    assert "- **Passion**:" in md_yaml
    assert "- **Decision/Commitment**:" in md_yaml
    assert "- hasComponent → Intimacy" in md_yaml
    assert "- hasType →" in md_yaml
    assert "Nonlove" in md_yaml
    assert "Consummate Love" in md_yaml

    print("\n>>> All OKF assertions passed successfully!")

if __name__ == "__main__":
    test_sternberg_love_okf()
