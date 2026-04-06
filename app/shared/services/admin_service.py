from datetime import datetime, UTC
from pathlib import Path
import shutil

import requests
from fastapi import UploadFile

from config import settings
from rag.client import get_chroma_client, get_collection
from rag.ingest import ingest_knowledge
from rag.loaders import SUPPORTED_EXTENSIONS, list_documents


class AdminService:
    @staticmethod
    def reindex() -> dict:
        return ingest_knowledge()

    @staticmethod
    def _ensure_knowledge_dir() -> Path:
        settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
        return settings.knowledge_dir

    @staticmethod
    def _resolve_knowledge_path(relative_path: str, knowledge_dir: Path) -> Path:
        requested = Path((relative_path or "").strip())
        if not requested.parts:
            raise ValueError("Path dokumen tidak valid")
        if requested.is_absolute():
            raise ValueError("Path dokumen harus relatif terhadap folder knowledge")

        target_path = (knowledge_dir / requested).resolve()
        try:
            target_path.relative_to(knowledge_dir.resolve())
        except ValueError as exc:
            raise ValueError("Path dokumen berada di luar folder knowledge") from exc

        return target_path

    @staticmethod
    def save_uploaded_documents(files: list[UploadFile]) -> dict:
        target_dir = AdminService._ensure_knowledge_dir()
        uploaded: list[str] = []
        skipped: list[dict] = []

        for file in files:
            filename = Path(file.filename or "").name
            if not filename:
                skipped.append({"file": "unknown", "reason": "Filename kosong"})
                continue

            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                skipped.append({"file": filename, "reason": f"Format tidak didukung ({suffix})"})
                continue

            destination = target_dir / filename
            with destination.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            uploaded.append(filename)

        return {
            "uploaded": uploaded,
            "uploaded_count": len(uploaded),
            "skipped": skipped,
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        }

    @staticmethod
    def delete_document(relative_path: str) -> dict:
        knowledge_dir = AdminService._ensure_knowledge_dir()
        target_path = AdminService._resolve_knowledge_path(relative_path, knowledge_dir)

        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError("Dokumen tidak ditemukan")

        if target_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("Format dokumen tidak didukung untuk dihapus")

        indexed_chunk_count = 0
        chunk_ids: list[str] = []

        try:
            collection = get_collection()
            payload = collection.get(where={"path": str(target_path)}, include=[])
            chunk_ids = payload.get("ids", []) or []
        except Exception:
            chunk_ids = []

        target_path.unlink()

        cleanup_error: Exception | None = None
        if chunk_ids:
            try:
                collection = get_collection()
                collection.delete(ids=chunk_ids)
                indexed_chunk_count = len(chunk_ids)
            except Exception as exc:
                cleanup_error = exc

        if cleanup_error is not None:
            raise RuntimeError(
                "Dokumen berhasil dihapus dari folder knowledge, tetapi cleanup index gagal. Jalankan reindex."
            ) from cleanup_error

        return {
            "deleted": str(target_path.relative_to(knowledge_dir)),
            "removed_chunks": indexed_chunk_count,
        }

    @staticmethod
    def get_monitoring_status() -> dict:
        services: list[dict] = []

        services.append(
            {
                "name": "app",
                "label": "Active",
                "status": "active",
                "detail": "API berjalan",
            }
        )

        try:
            response = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            services.append(
                {
                    "name": "ollama",
                    "label": "Active",
                    "status": "active",
                    "detail": f"Model terdeteksi: {len(models)}",
                }
            )
        except Exception as exc:
            services.append(
                {
                    "name": "ollama",
                    "label": "Warning",
                    "status": "warning",
                    "detail": f"Tidak tersambung: {exc}",
                }
            )

        try:
            client = get_chroma_client()
            _ = client.heartbeat()
            collection = get_collection()
            vector_count = collection.count()
            services.append(
                {
                    "name": "chroma",
                    "label": "Active",
                    "status": "active",
                    "detail": f"Vector tersimpan: {vector_count}",
                }
            )
        except Exception as exc:
            services.append(
                {
                    "name": "chroma",
                    "label": "Warning",
                    "status": "warning",
                    "detail": f"Tidak tersambung: {exc}",
                }
            )

        doc_count = len(list_documents(AdminService._ensure_knowledge_dir()))
        services.append(
            {
                "name": "knowledge",
                "label": "Active" if doc_count > 0 else "Warning",
                "status": "active" if doc_count > 0 else "warning",
                "detail": f"Dokumen terdeteksi: {doc_count}",
            }
        )

        overall = "active" if all(s["status"] == "active" for s in services) else "warning"
        return {
            "overall": overall,
            "overall_label": "Active" if overall == "active" else "Warning",
            "services": services,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _normalize_metadata_path(raw_path: str | None, knowledge_dir: Path) -> str | None:
        if not raw_path:
            return None

        path_obj = Path(raw_path)
        if path_obj.is_absolute():
            try:
                return str(path_obj.relative_to(knowledge_dir))
            except ValueError:
                return path_obj.name
        return str(path_obj)

    @staticmethod
    def get_knowledge_summary() -> dict:
        knowledge_dir = AdminService._ensure_knowledge_dir()
        documents = list_documents(knowledge_dir)
        source_paths = [str(path.relative_to(knowledge_dir)) for path in documents]
        source_set = set(source_paths)

        indexed_source_set: set[str] = set()
        chunk_by_source: dict[str, int] = {}
        chunks_total = 0
        index_status = "active"
        index_detail = "Index siap digunakan"

        try:
            collection = get_collection()
            chunks_total = collection.count()
            payload = collection.get(include=["metadatas"])
            metadatas = payload.get("metadatas", [])

            for metadata in metadatas:
                normalized = AdminService._normalize_metadata_path(metadata.get("path"), knowledge_dir)
                if not normalized:
                    normalized = metadata.get("source")
                if not normalized:
                    continue

                indexed_source_set.add(normalized)
                chunk_by_source[normalized] = chunk_by_source.get(normalized, 0) + 1
        except Exception as exc:
            index_status = "warning"
            index_detail = f"Index tidak tersedia: {exc}"

        indexed_known_sources = indexed_source_set.intersection(source_set)
        indexed_documents = len(indexed_known_sources)
        total_documents = len(source_paths)
        unindexed_sources = sorted(source_set - indexed_known_sources)

        coverage_pct = 0
        if total_documents > 0:
            coverage_pct = round((indexed_documents / total_documents) * 100)

        if total_documents == 0:
            readiness = "warning"
            readiness_label = "Belum ada knowledge"
        elif unindexed_sources:
            readiness = "warning"
            readiness_label = "Perlu reindex"
        elif index_status == "warning":
            readiness = "warning"
            readiness_label = "Index bermasalah"
        else:
            readiness = "active"
            readiness_label = "Knowledge siap"

        document_rows = []
        for document_path in documents:
            relative_path = str(document_path.relative_to(knowledge_dir))
            is_indexed = relative_path in indexed_known_sources
            document_rows.append(
                {
                    "path": relative_path,
                    "document": relative_path,
                    "chunks": chunk_by_source.get(relative_path) if is_indexed else None,
                    "status": "indexed" if is_indexed else "pending",
                    "updated_at": datetime.fromtimestamp(document_path.stat().st_mtime, UTC).isoformat(),
                }
            )

        document_rows.sort(key=lambda item: (item["status"] != "indexed", item["document"].lower()))

        top_sources = sorted(
            [
                {"source": row["document"], "chunks": row["chunks"]}
                for row in document_rows
                if row["status"] == "indexed" and row["chunks"] is not None
            ],
            key=lambda item: item["chunks"],
            reverse=True,
        )[:6]

        return {
            "readiness": readiness,
            "readiness_label": readiness_label,
            "coverage_pct": coverage_pct,
            "total_documents": total_documents,
            "indexed_documents": indexed_documents,
            "unindexed_documents": len(unindexed_sources),
            "chunks_total": chunks_total,
            "unindexed_sources": unindexed_sources[:8],
            "top_sources": top_sources,
            "documents": document_rows,
            "index_status": index_status,
            "index_detail": index_detail,
            "checked_at": datetime.now(UTC).isoformat(),
        }
