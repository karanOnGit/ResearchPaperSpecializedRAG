import os
from pathlib import Path
from typing import Dict, Any, List
try:
    import pymupdf as fitz
except ImportError:
    import fitz

class PDFLoader:
    """PDF document loader using PyMuPDF (fitz)."""

    def __init__(self, file_path: str):
        self.file_path = str(file_path)
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"PDF file not found: {self.file_path}")

    def load(self) -> Dict[str, Any]:
        """Extract pages, text, and metadata from PDF."""
        doc = fitz.open(self.file_path)
        filename = Path(self.file_path).name
        
        meta = doc.metadata or {}
        title = meta.get("title") or filename.replace(".pdf", "").replace("_", " ").title()
        author = meta.get("author") or "Unknown Author"

        pages_data: List[Dict[str, Any]] = []
        full_text_parts: List[str] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_text = page.get_text("text").strip()
            if page_text:
                pages_data.append({
                    "page_number": page_idx + 1,
                    "text": page_text,
                })
                full_text_parts.append(page_text)

        doc.close()

        return {
            "title": title,
            "source_type": "pdf",
            "source_path_or_url": self.file_path,
            "author": author,
            "total_pages": len(pages_data),
            "pages": pages_data,
            "raw_text": "\n\n".join(full_text_parts),
            "metadata": {
                "file_size": os.path.getsize(self.file_path),
                "format": meta.get("format", "PDF"),
                "creator": meta.get("creator", ""),
            }
        }
