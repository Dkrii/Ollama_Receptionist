from pathlib import Path
from typing import List, Dict

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _iter_docx_blocks(parent):
    if isinstance(parent, DocxDocument):
        parent_element = parent.element.body
    elif isinstance(parent, _Cell):
        parent_element = parent._tc
    else:
        raise TypeError(f"Unsupported parent type: {type(parent)!r}")

    for child in parent_element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _normalize_docx_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _read_docx_table(table: Table) -> list[str]:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            cell_parts: list[str] = []
            for block in _iter_docx_blocks(cell):
                if isinstance(block, Paragraph):
                    text = _normalize_docx_text(block.text)
                    if text:
                        cell_parts.append(text)
                else:
                    nested_rows = _read_docx_table(block)
                    if nested_rows:
                        cell_parts.append(" ; ".join(nested_rows))

            cell_text = " ".join(cell_parts).strip()
            if cell_text:
                cells.append(cell_text)

        if cells:
            rows.append(" | ".join(cells))

    return rows


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    parts: list[str] = []

    for block in _iter_docx_blocks(doc):
        if isinstance(block, Paragraph):
            text = _normalize_docx_text(block.text)
            if text:
                parts.append(text)
            continue

        parts.extend(_read_docx_table(block))

    return "\n".join(parts)


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


def _normalize_paragraphs(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    paragraphs = _normalize_paragraphs(text)
    if not paragraphs:
        return []

    chunks: List[str] = []
    current_parts: List[str] = []
    current_length = 0

    for paragraph in paragraphs:
        paragraph_length = len(paragraph)

        if paragraph_length >= chunk_size:
            if current_parts:
                chunks.append("\n".join(current_parts))
                current_parts = []
                current_length = 0

            start = 0
            while start < paragraph_length:
                end = min(start + chunk_size, paragraph_length)
                piece = paragraph[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= paragraph_length:
                    break
                start = max(0, end - overlap)
            continue

        projected_length = current_length + paragraph_length + (1 if current_parts else 0)
        if projected_length > chunk_size and current_parts:
            chunks.append("\n".join(current_parts))

            overlap_parts: List[str] = []
            overlap_length = 0
            for part in reversed(current_parts):
                part_length = len(part) + (1 if overlap_parts else 0)
                if overlap_parts and overlap_length + part_length > overlap:
                    break
                overlap_parts.insert(0, part)
                overlap_length += part_length

            current_parts = overlap_parts
            current_length = sum(len(part) for part in current_parts) + max(0, len(current_parts) - 1)

        current_parts.append(paragraph)
        current_length += paragraph_length + (1 if len(current_parts) > 1 else 0)

    if current_parts:
        chunks.append("\n".join(current_parts))

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
