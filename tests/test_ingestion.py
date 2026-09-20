import os
from pathlib import Path
from app.ingestion.pdf_loader import PDFLoader
from app.ingestion.markdown_loader import MarkdownLoader
from app.processing.cleaner import TextCleaner
from app.processing.chunker import TextChunker

def test_markdown_loader_and_chunker():
    sample_md = Path("data/samples/attention_research.md")
    assert sample_md.exists()

    loader = MarkdownLoader(str(sample_md))
    doc_data = loader.load()

    assert doc_data["title"] == "Attention Is All You Need: Architecture & Retrieval"
    assert doc_data["source_type"] == "markdown"
    assert len(doc_data["pages"]) > 0

    # Chunking
    chunker = TextChunker(chunk_size=500, chunk_overlap=100)
    chunks = chunker.chunk_document(doc_data, doc_id="test_doc_01")

    assert len(chunks) > 0
    assert chunks[0].doc_id == "test_doc_01"
    assert "Attention" in chunks[0].cleaned_content

def test_pdf_loader():
    sample_pdf = Path("data/samples/transformer_paper.pdf")
    assert sample_pdf.exists()

    loader = PDFLoader(str(sample_pdf))
    doc_data = loader.load()

    assert doc_data["source_type"] == "pdf"
    assert doc_data["total_pages"] == 1
    assert "Open Knowledge Format" in doc_data["raw_text"]

if __name__ == "__main__":
    test_markdown_loader_and_chunker()
    test_pdf_loader()
    print("Ingestion tests passed!")
