class WebPageService:
    @staticmethod
    def dev_template() -> str:
        return "home/index.html"

    @staticmethod
    def home_template() -> str:
        return "kiosk/index.html"

    @staticmethod
    def admin_template() -> str:
        return "admin/index.html"
