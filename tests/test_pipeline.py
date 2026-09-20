from pathlib import Path
from app.engine import ResearchKnowledgeEngine

def test_full_pipeline():
    engine = ResearchKnowledgeEngine()

    # Ingest Markdown document
    sample_md = Path("data/samples/attention_research.md")
    md_res = engine.ingest_markdown_or_text(str(sample_md))
    assert md_res["status"] == "success"
    assert md_res["chunks_count"] > 0
    assert md_res["concepts_count"] > 0

    # Ingest PDF document
    sample_pdf = Path("data/samples/transformer_paper.pdf")
    pdf_res = engine.ingest_pdf(str(sample_pdf))
    assert pdf_res["status"] == "success"
    assert pdf_res["chunks_count"] > 0

    # Verify Graph
    graph = engine.get_knowledge_graph()
    assert len(graph["nodes"]) > 0

    # Verify System Stats
    stats = engine.get_system_stats()
    assert stats["mongodb"]["counts"]["documents"] >= 2
    assert stats["mongodb"]["counts"]["concepts"] > 0
    assert stats["vector_index"]["total_chunks"] > 0

    # Run Research Query
    query = "How does Multi-Head Attention relate to Scaled Dot-Product Attention?"
    answer = engine.research_query(query)

    assert answer.query == query
    assert len(answer.answer) > 0
    assert len(answer.sources) > 0
    assert len(answer.citations) > 0
    assert len(answer.related_concepts) > 0
    assert answer.confidence_provenance.score > 0

    print("Pipeline test successful!")
    print(f"Synthesized Answer: {answer.answer[:200]}...")
    print(f"Citations: {len(answer.citations)}")
    print(f"Sources: {len(answer.sources)}")
    print(f"Related Concepts: {[c.name for c in answer.related_concepts]}")
    print(f"Confidence: {answer.confidence_provenance.rating} ({answer.confidence_provenance.score * 100:.0f}%)")

if __name__ == "__main__":
    test_full_pipeline()
