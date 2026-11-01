from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from resourcly.bootstrap import Services, Settings, open_services
from resourcly.errors import InvalidDocument, NotFound, UnreadableDrawing
from resourcly.models import DrawingSummary, Issue

DocumentBody = Annotated[Any, Body()]
Dpi = Annotated[int, Query(ge=36, le=400)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with open_services(settings) as services:
            app.state.services = services
            yield

    app = FastAPI(title="Resourcly", lifespan=lifespan)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, error: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(UnreadableDrawing)
    async def unreadable(_: Request, error: UnreadableDrawing) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(InvalidDocument)
    async def invalid(_: Request, error: InvalidDocument) -> JSONResponse:
        issues = [issue.model_dump() for issue in error.issues]
        return JSONResponse({"detail": str(error), "issues": issues}, status_code=422)

    def services(request: Request) -> Services:
        return request.app.state.services

    @app.get("/api/drawings")
    def list_drawings(request: Request) -> list[DrawingSummary]:
        return services(request).gold.list_drawings()

    @app.get("/api/drawings/{drawing}")
    def get_drawing(request: Request, drawing: str) -> dict[str, Any]:
        return services(request).gold.load(drawing)

    @app.put("/api/drawings/{drawing}")
    def put_drawing(request: Request, drawing: str, document: DocumentBody) -> dict[str, Any]:
        return services(request).gold.save(drawing, document).model_dump(mode="json")

    @app.post("/api/drawings/{drawing}/check")
    def check_drawing(request: Request, drawing: str, document: DocumentBody) -> list[Issue]:
        return services(request).gold.check(drawing, document)

    @app.get("/api/drawings/{drawing}/pages/{page}.png")
    def page_image(request: Request, drawing: str, page: int, dpi: Dpi = 150) -> Response:
        png = services(request).gold.render_page(drawing, page, dpi)
        return Response(
            png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
        )

    if settings.ui_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.ui_dist, html=True), name="ui")

    return app
