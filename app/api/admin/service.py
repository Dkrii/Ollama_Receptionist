from fastapi import UploadFile

from shared.services.admin_service import AdminService


class AdminAppService:
    @staticmethod
    def reindex() -> dict:
        return AdminService.reindex()

    @staticmethod
    def upload_documents(files: list[UploadFile]) -> dict:
        return AdminService.save_uploaded_documents(files)

    @staticmethod
    def monitoring_status() -> dict:
        return AdminService.get_monitoring_status()
