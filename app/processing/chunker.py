import uuid
from typing import List, Dict, Any
from app.okf.models import DocumentChunk
from app.processing.cleaner import TextCleaner

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError:
        class RecursiveCharacterTextSplitter:
            def __init__(self, chunk_size=800, chunk_overlap=100, separators=None):
                self.chunk_size = chunk_size
                self.chunk_overlap = chunk_overlap
                self.separators = separators or ["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]

            def split_text(self, text: str) -> List[str]:
                chunks = []
                start = 0
                text_len = len(text)
                while start < text_len:
                    end = min(start + self.chunk_size, text_len)
                    if end < text_len:
                        for sep in self.separators:
                            last_sep = text.rfind(sep, start, end)
                            if last_sep != -1 and last_sep > start + (self.chunk_size // 3):
                                end = last_sep + len(sep)
                                break
                    chunk = text[start:end].strip()
                    if chunk:
                        chunks.append(chunk)
                    if end >= text_len:
                        break
                    # Ensure start always advances by at least max(1, chunk_size // 2)
                    next_start = end - self.chunk_overlap
                    if next_start <= start:
                        next_start = start + max(1, self.chunk_size // 2)
                    start = next_start
                return chunks

class TextChunker:
    """Chunks documents into semantic pieces while preserving page/section provenance."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", ". ", " ", ""]
        )

    def chunk_document(self, doc_data: Dict[str, Any], doc_id: str) -> List[DocumentChunk]:
        """Split document pages into typed DocumentChunk objects."""
        chunks: List[DocumentChunk] = []
        global_chunk_idx = 0
        pages = doc_data.get("pages", [])
        source_title = doc_data.get("title", "Untitled Document")
        source_type = doc_data.get("source_type", "unknown")

        if not pages and doc_data.get("raw_text"):
            pages = [{"page_number": 1, "text": doc_data["raw_text"], "section": "General"}]

        for page in pages:
            raw_page_text = page.get("text", "")
            page_num = page.get("page_number", 1)
            section = page.get("section", "")
            cleaned_page_text = TextCleaner.clean(raw_page_text)

            if not cleaned_page_text:
                continue

            page_splits = self.splitter.split_text(cleaned_page_text)

            for split_idx, split_text in enumerate(page_splits):
                chunk_id = f"{doc_id}_c{global_chunk_idx:04d}"
                # Rough token count: approx 4 chars per token
                token_count = max(1, len(split_text) // 4)

                chunk = DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    source_title=source_title,
                    source_type=source_type,
                    content=split_text,
                    cleaned_content=split_text,
                    page_number=page_num,
                    section=section,
                    chunk_index=global_chunk_idx,
                    token_count=token_count,
                    concepts=[],
                    metadata={
                        "source_path_or_url": doc_data.get("source_path_or_url", ""),
                        "split_index": split_idx
                    }
                )
                chunks.append(chunk)
                global_chunk_idx += 1

        return chunks
