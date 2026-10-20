"""The built SPA, served on the same origin as the API."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

NOT_THE_SPA = frozenset({"api", "telegram", "healthz", "docs", "redoc", "openapi.json"})


def serve_web(app: FastAPI, dist: Path) -> None:
    """Serve `dist`'s assets and files, and index.html for any other GET; register it last."""
    root = dist.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets", check_dir=False), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.split("/", 1)[0] in NOT_THE_SPA:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html")
