from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from resourcly.bootstrap import Services, Settings, open_services
from resourcly.errors import (
    EmptyRequest,
    InvalidDocument,
    NotFound,
    UnreadableDrawing,
    UploadTooLarge,
)
from resourcly.models import DrawingSummary, Issue, RequestRecord, RequestTrace

DocumentBody = Annotated[Any, Body()]
Dpi = Annotated[int, Query(ge=36, le=400)]
Side = Annotated[int, Query(ge=32, le=2048)]
MB = 1024 * 1024
Screen = Literal["chat", "annotation"]
# The addresses the chat app routes in the browser; a reload of one must get its page too.
CHAT_ADDRESSES = ("/chat", "/requests", "/requests/{rest:path}")


def create_app(settings: Settings | None = None, screen: Screen = "chat") -> FastAPI:
    """The API, and the built screen at the root when there is one: the chat or the label screen."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with open_services(settings) as services:
            app.state.services = services
            services.recover()
            services.load_demos()
            yield

    app = FastAPI(title="Resourcly", lifespan=lifespan)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, error: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(UnreadableDrawing)
    async def unreadable(_: Request, error: UnreadableDrawing) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(EmptyRequest)
    async def empty(_: Request, error: EmptyRequest) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(UploadTooLarge)
    async def too_large(_: Request, error: UploadTooLarge) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=413)

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

    @app.get("/api/agent")
    def agent(request: Request) -> dict[str, str | int | float]:
        """The versions the agent runs and the upload caps, so a client can check before sending."""
        found = services(request)
        return {
            "reader": found.reader_name,
            "router": found.router_name,
            "failure": found.failure_name,
            "answer": found.answer_name,
            "max_file_mb": round(settings.max_upload_bytes / MB, 2),
            "max_files": settings.max_files,
        }

    @app.post("/api/requests", status_code=202)
    async def send(
        request: Request,
        text: Annotated[str, Form()] = "",
        files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI copies defaults
    ) -> RequestRecord:
        """One chat message: text, files, or both. The work runs in the background; poll it."""
        if len(files) > settings.max_files:
            raise UploadTooLarge(
                f"A message can carry at most {settings.max_files} files;"
                f" this one has {len(files)}."
            )
        limit = settings.max_upload_bytes
        contents = []
        for file in files:
            name = file.filename or "file"
            # Never read more than the cap, however large the file is.
            data = await file.read(limit + 1)
            if len(data) > limit:
                size = (file.size or len(data)) / MB
                raise UploadTooLarge(
                    f"{name} is {size:.1f} MB;"
                    f" each file can be at most {round(limit / MB, 2):g} MB."
                )
            contents.append((name, data))
        return await run_in_threadpool(services(request).agent.submit, text, contents)

    @app.get("/api/requests")
    def list_requests(
        request: Request, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[RequestRecord]:
        return services(request).agent.list(limit)

    @app.get("/api/requests/{request_id}")
    def get_request(request: Request, request_id: str) -> RequestRecord:
        return services(request).agent.load(request_id)

    @app.get("/api/requests/{request_id}/trace")
    def request_trace(request: Request, request_id: str) -> RequestTrace:
        return services(request).traces.lookup(request_id)

    @app.get("/api/requests/{request_id}/items/{item_id}/result")
    def item_result(
        request: Request, request_id: str, item_id: str, download: bool = False
    ) -> JSONResponse:
        document = services(request).agent.result(request_id, item_id)
        headers = {"Content-Disposition": f'attachment; filename="{item_id}.json"'}
        return JSONResponse(document, headers=headers if download else None)

    @app.get("/api/requests/{request_id}/items/{item_id}/pages/{page}.png")
    def item_page(
        request: Request, request_id: str, item_id: str, page: int, dpi: Dpi = 150
    ) -> Response:
        """One page of an uploaded file, a photo included, for a screen to place values on."""
        png = services(request).agent.page(request_id, item_id, page, dpi)
        return Response(
            png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
        )

    @app.get("/api/reports/{report}/figures/{number}.png")
    def report_figure(
        request: Request, report: str, number: int, max_side: Side = 1024
    ) -> Response:
        """A report figure a photo answer cites, such as 18-061 fig05 at 18-061/figures/5.png."""
        png = services(request).reports.figure_image(report, number, max_side)
        return Response(
            png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
        )

    dist = settings.chat_ui_dist if screen == "chat" else settings.annotation_ui_dist
    if dist.is_dir():
        if screen == "chat":
            index = dist / "index.html"
            for path in CHAT_ADDRESSES:
                app.add_api_route(path, lambda: FileResponse(index), include_in_schema=False)
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")

    return app
