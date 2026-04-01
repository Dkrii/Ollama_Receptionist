from pathlib import Path
from typing import List, Dict

from docx import Document
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _read_txt(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def list_documents(knowledge_dir: Path) -> List[Path]:
    documents: List[Path] = []
    for path in knowledge_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            documents.append(path)
    return sorted(documents)


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []

    chunks: List[str] = []
    start = 0
    length = len(cleaned)

    while start < length:
        end = min(start + chunk_size, length)
        chunk = cleaned[start:end]
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(0, end - overlap)

    return chunks


def build_chunks(path: Path, text: str, chunk_size: int, overlap: int) -> List[Dict]:
    chunks = chunk_text(text, chunk_size, overlap)
    records: List[Dict] = []

    for idx, chunk in enumerate(chunks):
        records.append(
            {
                "id": f"{path.name}:{idx}",
                "content": chunk,
                "metadata": {
                    "source": str(path.name),
                    "path": str(path),
                    "chunk_index": idx,
                },
            }
        )

    return records
