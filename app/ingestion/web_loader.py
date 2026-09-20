from typing import Dict, Any, List
import requests
from bs4 import BeautifulSoup
import trafilatura

class WebLoader:
    """Web document loader for articles, research posts, and documentation URLs."""

    def __init__(self, url: str, timeout: int = 15):
        self.url = url.strip()
        self.timeout = timeout

    def load(self) -> Dict[str, Any]:
        """Fetch URL and extract clean body content and metadata."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(self.url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        html_content = response.text

        # Extract using trafilatura for high precision
        extracted_text = trafilatura.extract(
            html_content,
            include_comments=False,
            include_tables=True,
            include_links=False,
            output_format="txt"
        )
        
        metadata = trafilatura.extract_metadata(html_content)
        title = ""
        author = ""
        published_date = ""

        if metadata:
            title = metadata.title or ""
            author = metadata.author or ""
            published_date = metadata.date or ""

        # Fallback to BeautifulSoup if trafilatura extracts too little
        if not extracted_text or len(extracted_text.strip()) < 50:
            soup = BeautifulSoup(html_content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
                tag.decompose()
            if not title and soup.title:
                title = soup.title.string or ""
            extracted_text = soup.get_text(separator="\n\n").strip()

        if not title:
            # Derive title from URL
            clean_slug = self.url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")
            title = clean_slug.title() if clean_slug else self.url

        pages_data: List[Dict[str, Any]] = [
            {"page_number": 1, "text": extracted_text or ""}
        ]

        return {
            "title": title,
            "source_type": "url",
            "source_path_or_url": self.url,
            "author": author,
            "published_date": published_date,
            "total_pages": 1,
            "pages": pages_data,
            "raw_text": extracted_text or "",
            "metadata": {
                "status_code": response.status_code,
                "url": self.url,
            }
        }
