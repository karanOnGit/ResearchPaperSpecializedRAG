import re
import unicodedata

class TextCleaner:
    """Text cleaner for research document ingestion."""

    @staticmethod
    def clean(text: str) -> str:
        if not text:
            return ""

        # Normalize unicode (NFC)
        text = unicodedata.normalize("NFC", text)

        # Fix unicode quotation marks and dashes
        text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        text = text.replace("—", " - ").replace("–", " - ")

        # Remove null bytes and non-printable control characters (except newline, tab)
        text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or unicodedata.category(ch)[0] != "C")

        # Remove orphan page number patterns like "Page 12 of 30" or standalone numbers on newlines
        text = re.sub(r'(?i)\bpage\s+\d+\s+(?:of|\/)\s+\d+\b', '', text)
        text = re.sub(r'(?i)\bpage\s+\d+\b', '', text)

        # Normalize carriage returns
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Replace excessive spaces and tabs on lines
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split("\n")]

        # Collapse more than 2 consecutive newlines into 2
        cleaned_lines = []
        blank_counter = 0
        for line in lines:
            if not line:
                blank_counter += 1
                if blank_counter <= 2:
                    cleaned_lines.append("")
            else:
                blank_counter = 0
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()
