import os
from pathlib import Path
from typing import Dict, Any, List
import yaml

class MarkdownLoader:
    """Markdown and Plain Text document loader."""

    def __init__(self, file_path_or_content: str, is_raw_text: bool = False, title: str = ""):
        self.is_raw_text = is_raw_text
        self.title = title
        if is_raw_text:
            self.content = file_path_or_content
            self.file_path = "pasted_text.md"
        else:
            self.file_path = str(file_path_or_content)
            if not os.path.exists(self.file_path):
                raise FileNotFoundError(f"Markdown file not found: {self.file_path}")
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                self.content = f.read()

    def load(self) -> Dict[str, Any]:
        """Extract sections, text, and frontmatter metadata."""
        text = self.content
        frontmatter = {}
        
        # Check for YAML frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    text = parts[2].strip()
                except Exception:
                    pass

        # Derive title
        derived_title = self.title
        if not derived_title and isinstance(frontmatter, dict):
            derived_title = frontmatter.get("title")

        if not derived_title:
            # Check for first h1 `# Title`
            for line in text.splitlines():
                line_s = line.strip()
                if line_s.startswith("# "):
                    derived_title = line_s[2:].strip()
                    break

        if not derived_title:
            derived_title = Path(self.file_path).stem.replace("_", " ").title()

        # Split into sections based on markdown headers
        sections = []
        current_section = "Introduction"
        current_lines = []

        for line in text.splitlines():
            if line.startswith("#"):
                if current_lines:
                    sections.append({
                        "section": current_section,
                        "text": "\n".join(current_lines).strip()
                    })
                    current_lines = []
                current_section = line.lstrip("#").strip()
            current_lines.append(line)

        if current_lines:
            sections.append({
                "section": current_section,
                "text": "\n".join(current_lines).strip()
            })

        pages_data: List[Dict[str, Any]] = []
        for idx, sec in enumerate(sections):
            pages_data.append({
                "page_number": idx + 1,
                "section": sec["section"],
                "text": sec["text"]
            })

        return {
            "title": derived_title,
            "source_type": "markdown",
            "source_path_or_url": self.file_path,
            "author": frontmatter.get("author", "Unknown"),
            "published_date": str(frontmatter.get("date", "")),
            "total_pages": len(pages_data),
            "pages": pages_data,
            "raw_text": text,
            "metadata": {
                "frontmatter": frontmatter,
                "sections_count": len(sections)
            }
        }
