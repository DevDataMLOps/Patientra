"""Same-origin dashboard shell; aggregate data is fetched through protected APIs."""
from pathlib import Path

from fastapi.responses import FileResponse


ASSETS = Path(__file__).with_name("web")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'; object-src 'none'")


def register_dashboard(app):
    def asset(name, media_type):
        return FileResponse(ASSETS / name, media_type=media_type, headers={
            "Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
        })

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return asset("dashboard.html", "text/html")

    @app.get("/dashboard.css", include_in_schema=False)
    def stylesheet():
        return asset("dashboard.css", "text/css")

    @app.get("/dashboard.js", include_in_schema=False)
    def javascript():
        return asset("dashboard.js", "application/javascript")
