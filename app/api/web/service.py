class WebPageService:
    @staticmethod
    def home_template() -> str:
        return "dev/index.html"

    @staticmethod
    def admin_template() -> str:
        return "admin/index.html"
