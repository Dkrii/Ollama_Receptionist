import logging
from pathlib import Path
from typing import Dict

from config import settings
from infrastructure.chroma import get_collection, embed_texts
from modules.knowledge_base.documents import list_documents, read_document, build_chunks


_logger = logging.getLogger(__name__)


def ingest_knowledge(knowledge_dir: Path | None = None) -> Dict:
    target_dir = knowledge_dir or settings.knowledge_dir
    collection = get_collection()

    existing = collection.get(include=[])
    existing_ids = existing.get("ids", [])
    if existing_ids:
        collection.delete(ids=existing_ids)

    documents = list_documents(target_dir)
    total_chunks = 0

    for file_path in documents:
        text = read_document(file_path)
        records = build_chunks(
            file_path,
            text,
            chunk_size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )

        if not records:
            continue

        contents = [item["content"] for item in records]
        vectors = embed_texts(contents)

        collection.add(
            ids=[item["id"] for item in records],
            documents=contents,
            embeddings=vectors,
            metadatas=[item["metadata"] for item in records],
        )

        total_chunks += len(records)

    total_employees = _ingest_employees(collection)

    return {
        "documents": len(documents),
        "chunks": total_chunks,
        "employees": total_employees,
        "collection": settings.chroma_collection,
        "knowledge_dir": str(target_dir),
    }


def _ingest_employees(collection) -> int:
    try:
        from modules.tools.employee_directory import tool as emp_tool
        employees = emp_tool.list_employees()
    except Exception:
        _logger.warning("ingest.employees skipped — employee directory unavailable")
        return 0

    if not employees:
        return 0

    contents = []
    ids = []
    metadatas = []

    for emp in employees:
        text = f"Nama: {emp['nama']}\nJabatan: {emp['jabatan']}\nDepartemen: {emp['departemen']}"
        if emp.get("division"):
            text += f"\nDivisi: {emp['division']}"
        if emp.get("section"):
            text += f"\nSeksi: {emp['section']}"
        contents.append(text)
        ids.append(f"emp__{emp['id']}")
        metadatas.append({"source": "employee_directory", "employee_id": str(emp["id"])})

    vectors = embed_texts(contents)
    collection.add(ids=ids, documents=contents, embeddings=vectors, metadatas=metadatas)
    return len(employees)
