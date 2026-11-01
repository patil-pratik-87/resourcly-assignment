from pathlib import Path

from resourcly.adapters.stub_router import StubRouteAdapter
from resourcly.bootstrap import PROJECT_ROOT, Settings, open_services
from resourcly.models import Attachment, Route
from tests.conftest import CTC01, png

DATA = PROJECT_ROOT / "data"


def pdf(path: Path) -> Attachment:
    return Attachment(path.name, "application/pdf", path.read_bytes())


def test_a_pdf_drawn_in_vector_paths_is_a_drawing() -> None:
    verdict = StubRouteAdapter().decide(pdf(DATA / "drawings" / f"{CTC01}.pdf"))

    assert verdict.route == Route.DRAWING
    assert "1797 vector paths" in verdict.reason


def test_a_report_of_text_and_photos_fits_no_case() -> None:
    verdict = StubRouteAdapter().decide(pdf(DATA / "reports" / "ntsb_16-006.pdf"))

    assert verdict.route == Route.OTHER


def test_an_image_is_a_photo_and_text_alone_is_text() -> None:
    assert StubRouteAdapter().decide(Attachment("crack.png", "image/png", png())).route == (
        Route.PHOTO
    )
    assert StubRouteAdapter().decide(None).route == Route.TEXT


def test_an_unreadable_pdf_fits_no_case() -> None:
    broken = Attachment("broken.pdf", "application/pdf", b"%PDF-1.7 and then nothing")

    assert StubRouteAdapter().decide(broken).route == Route.OTHER


def test_the_stub_version_routes_without_a_model(settings: Settings) -> None:
    stub = settings.with_version("router", "stub-v0")
    with open_services(stub) as services:
        routing = services.router.route(None, pdf(DATA / "drawings" / f"{CTC01}.pdf"), "r1")
        name = services.router_name
        steps = [event.step for event in services.traces.lookup("r1").events]

    assert (routing.route, routing.layer) == (Route.DRAWING, "stub")
    assert name == "stub-v0 (stub)"
    assert steps == ["route.stub"]
