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
