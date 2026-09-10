import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from src.app.schemas.rag import RAGChunkSchema
from src.app.core.logging import logger


class DocumentChunker:
    """
    Document loader, text cleaner, and sliding-window chunker with metadata preservation.
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be lower than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @staticmethod
    def compute_file_checksum(file_path: Path) -> str:
        """Calculates SHA-256 hash of a file on disk."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def clean_text(raw_text: str) -> str:
        """Normalizes whitespace and cleans invalid characters while preserving paragraph structure."""
        if not raw_text:
            return ""
        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def build_document_id(file_path: Path, academic_year: str) -> str:
        safe_year = re.sub(r"[^A-Za-z0-9_-]+", "_", academic_year).strip("_")
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", file_path.stem).strip("_")
        return f"doc-{safe_year}-{safe_stem}"

    def extract_text_from_file(self, file_path: Path) -> List[Tuple[int, str]]:
        """
        Extracts text from file (PDF, TXT, MD).
        Returns a list of tuples: [(page_number, page_text)]
        """
        extension = file_path.suffix.lower()
        pages = []

        if extension == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(file_path))
                for idx, page in enumerate(reader.pages, 1):
                    extracted = page.extract_text() or ""
                    cleaned = self.clean_text(extracted)
                    if cleaned:
                        pages.append((idx, cleaned))
            except Exception as e:
                logger.error(f"Error reading PDF {file_path}: {e}")
        else:
            # TXT or Markdown file
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = self.clean_text(f.read())
                    if content:
                        pages.append((1, content))
            except Exception as e:
                logger.error(f"Error reading text file {file_path}: {e}")

        return pages

    def chunk_document(
        self,
        file_path: Path,
        academic_year: str
    ) -> List[RAGChunkSchema]:
        """
        Loads document, extracts text, computes checksum, and returns chunk objects.
        """
        checksum = self.compute_file_checksum(file_path)
        pages_text = self.extract_text_from_file(file_path)

        doc_id = self.build_document_id(file_path, academic_year)
        doc_type = file_path.suffix.lstrip(".").lower()
        chunks = []
        global_chunk_idx = 0

        for page_num, text in pages_text:
            if not text:
                continue

            # Perform sliding-window character/word chunking
            start = 0
            text_length = len(text)

            while start < text_length:
                end = start + self.chunk_size
                chunk_text = text[start:end]

                # Adjust boundary to end at sentence or space if possible
                if end < text_length:
                    last_space = chunk_text.rfind(" ")
                    if last_space > self.chunk_size // 2:
                        chunk_text = chunk_text[:last_space]
                        end = start + last_space

                chunk_text = chunk_text.strip()
                if len(chunk_text) > 20:  # Skip tiny fragments
                    chunk_id = f"{doc_id}-p{page_num}-c{global_chunk_idx}"
                    chunks.append(RAGChunkSchema(
                        chunk_id=chunk_id,
                        document_id=doc_id,
                        filename=file_path.name,
                        academic_year=academic_year,
                        page=page_num,
                        chunk_index=global_chunk_idx,
                        source_path=str(file_path),
                        text=chunk_text,
                        checksum=checksum,
                        document_type=doc_type
                    ))
                    global_chunk_idx += 1

                if end >= text_length:
                    break

                # Advance from the actual boundary. Using the terminal chunk length
                # here would otherwise walk one character at a time near EOF.
                start = max(start + 1, end - self.chunk_overlap)

        logger.info(f"Chunked document '{file_path.name}' into {len(chunks)} chunks.")
        return chunks
