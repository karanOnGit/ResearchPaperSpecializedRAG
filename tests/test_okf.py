# Unit test for OKF models and serialization
from app.okf.models import OKFConcept, OKFRelationship, OKFSource, OKFProvenance
from app.okf.serializer import OKFSerializer

def test_okf_concept_serialization():
    prov = OKFProvenance(
        source_id="doc_123",
        source_title="Attention Research",
        source_url="https://arxiv.org/abs/1706.03762",
        page_number=2,
        extractor="groq/llama-3.3-70b-versatile",
        confidence=0.95
    )

    rel = OKFRelationship(
        id="rel_01",
        source="Multi-Head Attention",
        target="Scaled Dot-Product Attention",
        relation_type="IMPLEMENTS",
        description="Multi-Head Attention implements Scaled Dot-Product Attention in parallel.",
        evidence_quote="Multi-Head Attention implements Scaled Dot-Product Attention in parallel."
    )

    concept = OKFConcept(
        id="concept_multi_head_attention",
        name="Multi-Head Attention",
        category="Mechanism",
        definition="An attention mechanism allowing joint representation across subspaces.",
        aliases=["MHA", "Parallel Attention"],
        provenance=prov,
        relationships=[rel],
        tags=["Mechanism", "NLP"]
    )

    # Serialize to Markdown + YAML
    md_yaml = OKFSerializer.concept_to_markdown_yaml(concept)
    assert "---" in md_yaml
    assert "okf_version: '1.0'" in md_yaml or 'okf_version: "1.0"' in md_yaml or "okf_version: 1.0" in md_yaml
    assert "Multi-Head Attention" in md_yaml
    assert "IMPLEMENTS" in md_yaml
    assert "Scaled Dot-Product Attention" in md_yaml

    # Parse back
    parsed = OKFSerializer.parse_markdown_yaml(md_yaml)
    assert parsed["frontmatter"]["name"] == "Multi-Head Attention"
    assert parsed["frontmatter"]["category"] == "Mechanism"
    assert len(parsed["frontmatter"]["relationships"]) == 1
    assert "## Definition" in parsed["body"]

def test_okf_source_serialization():
    source = OKFSource(
        id="doc_456",
        title="Attention Is All You Need",
        source_type="pdf",
        source_path_or_url="attention.pdf",
        author="Vaswani et al.",
        summary="Foundational transformer paper."
    )

    md_yaml = OKFSerializer.source_to_markdown_yaml(source)
    assert "Attention Is All You Need" in md_yaml
    assert "document_source" in md_yaml

if __name__ == "__main__":
    test_okf_concept_serialization()
    test_okf_source_serialization()
    print("OKF serialization tests passed!")
