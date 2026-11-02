"""Find the callouts on a drawing page from its vector paths, with no model.

The NIST drawings draw every annotation as vector paths in one colour, and nothing else on the
sheet uses it. Letters are filled paths with a hairline outline, or, on a drawing that writes its
callouts as text, the short text lines of the text layer. Frames (feature control frames
and datum feature boxes) are single closed four-corner paths stroked at the annotation line width.
`locate` turns those paths into one box per callout:

1. The annotation colour is the colour that holds the most letter-shaped paths, so blue is found,
   not assumed.
2. Every frame is a callout. A frame inside another frame (the flatness symbol is a small
   parallelogram) belongs to the outer one.
3. Each letter inside a frame belongs to that frame. This keeps the symbol cell, which is drawn
   with thin strokes rather than letters, inside the box.
4. The other letters are grouped into text callouts when they lie within `reach` letter sizes of
   each other. A frame is never merged with a text group, so stacked callouts stay apart.
5. A text group of one letter outside any frame is an axis or point label and is dropped.

Boxes are in points in the page as displayed (landscape).
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from resourcly.adapters.text_reader import callout_lines

Point = tuple[float, float]
Colour = tuple[float, float, float]


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def centre(self) -> Point:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    def grown(self, by: float) -> "Rect":
        return Rect(self.x0 - by, self.y0 - by, self.x1 + by, self.y1 + by)

    def union(self, other: "Rect") -> "Rect":
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersects(self, other: "Rect") -> bool:
        return (
            self.x0 <= other.x1
            and other.x0 <= self.x1
            and self.y0 <= other.y1
            and other.y0 <= self.y1
        )


@dataclass(frozen=True)
class Frame:
    """A closed four-corner path: a feature control frame or a datum feature box."""

    corners: tuple[Point, Point, Point, Point]

    @property
    def box(self) -> Rect:
        xs, ys = zip(*self.corners, strict=True)
        return Rect(min(xs), min(ys), max(xs), max(ys))

    def contains(self, point: Point) -> bool:
        """Whether the point is inside the quadrilateral, which may be slanted."""
        signs = set()
        for (ax, ay), (bx, by) in zip(
            self.corners, self.corners[1:] + self.corners[:1], strict=True
        ):
            cross = (bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax)
            if abs(cross) > 1e-9:
                signs.add(cross > 0)
        return len(signs) < 2


@dataclass(frozen=True)
class Callout:
    box: Rect
    framed: bool
    letters: int


@dataclass(frozen=True)
class PagePaths:
    letters: list[Rect]
    frames: list[Frame]
    letter_size: float


def locate(page: pymupdf.Page, reach: float = 2.0) -> list[Callout]:
    """One callout per frame or text group on the page, top to bottom, then left to right."""
    return group_callouts(page_paths(page), reach)


def page_paths(page: pymupdf.Page) -> PagePaths:
    """The letter boxes and frames drawn in the page's annotation colour, in displayed points."""
    drawings = page.get_drawings()
    colour = annotation_colour(drawings)
    matrix = page.rotation_matrix
    letters, frames = [], []
    for drawing in drawings:
        if colour is None or colour not in (_rgb(drawing.get("color")), _rgb(drawing.get("fill"))):
            continue
        if _letter_shaped(drawing):
            rect = drawing["rect"] * matrix
            letters.append(Rect(rect.x0, rect.y0, rect.x1, rect.y1))
        elif drawing["type"] == "s" and (drawing.get("width") or 0) >= 0.1:
            corners = _frame_corners(drawing["items"])
            if corners:
                frames.append(Frame(tuple(_point(p * matrix) for p in corners)))
    width, height = page.rect.width, page.rect.height
    for _, (x0, y0, x1, y1) in callout_lines(page):
        letters.append(Rect(x0 * width, y0 * height, x1 * width, y1 * height))
    sizes = sorted(max(min(r.x1 - r.x0, r.y1 - r.y0), 1.0) for r in letters)
    letter_size = sizes[len(sizes) // 2] if sizes else 1.0
    return PagePaths(letters, frames, letter_size)


def annotation_colour(drawings: Sequence[dict]) -> Colour | None:
    """The colour that holds the most letter-shaped paths, or None when there are none."""
    counts = Counter(_rgb(d.get("fill")) for d in drawings if _letter_shaped(d))
    counts.pop(None, None)
    return counts.most_common(1)[0][0] if counts else None


def group_callouts(paths: PagePaths, reach: float = 2.0) -> list[Callout]:
    size = paths.letter_size
    frames = _outer_frames(paths.frames, size)
    framed: list[list[Rect]] = [[] for _ in frames]
    loose = []
    for letter in paths.letters:
        owner = next((i for i, f in enumerate(frames) if f.contains(letter.centre)), None)
        if owner is None:
            loose.append(letter)
        else:
            framed[owner].append(letter)
    callouts = [
        Callout(_union([frame.box, *inside]), True, len(inside))
        for frame, inside in zip(frames, framed, strict=True)
    ]
    for group in _join_lines(_cluster(loose, reach * size), size):
        box = _union(group)
        if len(group) == 1 and max(box.x1 - box.x0, box.y1 - box.y0) < 3 * size:
            continue
        callouts.append(Callout(box, False, len(group)))
    return sorted(callouts, key=lambda c: (round(c.box.y0), c.box.x0))


def _join_lines(groups: list[list[Rect]], letter_size: float) -> list[list[Rect]]:
    """Join text groups that lie on one text line less than 4 letter sizes apart.

    A gap in a line, such as the dash in "⌀34.8 - 35.2", can be wider than the grouping reach.
    Two groups are on one line when both run the same way and each centre lies on the other's
    line; stacked lines run the same way but sit side by side, so they stay apart.
    """
    groups = list(groups)
    joined = True
    while joined:
        joined = False
        pairs = [(i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))]
        for first, second in pairs:
            if _same_line(groups[first], groups[second], letter_size):
                groups[first] = groups[first] + groups.pop(second)
                joined = True
                break
    return groups


def _same_line(a: list[Rect], b: list[Rect], letter_size: float) -> bool:
    if len(a) < 3 or len(b) < 3:
        return False
    if not _union(a).grown(4 * letter_size).intersects(_union(b)):
        return False
    (ux, uy), (vx, vy) = _direction(a), _direction(b)
    if abs(ux * vy - uy * vx) > 0.17:  # more than 10 degrees apart
        return False
    (ax, ay), (bx, by) = _union(a).centre, _union(b).centre
    return abs((bx - ax) * uy - (by - ay) * ux) < letter_size


def _direction(letters: list[Rect]) -> Point:
    """The unit direction the letters run in, from the main axis of their centres."""
    xs, ys = zip(*(r.centre for r in letters), strict=True)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return math.cos(angle), math.sin(angle)


def _outer_frames(frames: list[Frame], letter_size: float) -> list[Frame]:
    """Frames big enough to hold a letter, without those that sit inside another frame."""
    big = [f for f in frames if max(f.box.x1 - f.box.x0, f.box.y1 - f.box.y0) >= 1.5 * letter_size]
    return [
        f
        for f in big
        if not any(o is not f and _area(o) > _area(f) and o.contains(f.box.centre) for o in big)
    ]


def _cluster(letters: list[Rect], gap: float) -> list[list[Rect]]:
    parent = list(range(len(letters)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grown = [r.grown(gap) for r in letters]
    for i in range(len(letters)):
        for j in range(i + 1, len(letters)):
            if grown[i].intersects(letters[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Rect]] = {}
    for i, letter in enumerate(letters):
        groups.setdefault(find(i), []).append(letter)
    return list(groups.values())


def _letter_shaped(drawing: dict) -> bool:
    """Smaller than 12 pt both ways, and filled with a hairline outline or with no outline.

    A fill with no outline is a letter only when its outline has at least 6 segments, because
    arrowheads are filled triangles.
    """
    rect = drawing["rect"]
    if rect.width >= 12 or rect.height >= 12:
        return False
    if drawing["type"] == "fs":
        return (drawing.get("width") or 0) < 0.1
    return drawing["type"] == "f" and len(drawing["items"]) >= 6


def _frame_corners(items: list[tuple]) -> list[pymupdf.Point] | None:
    """The four corners of a frame path, or None when the path is not a frame.

    A frame is a rectangle, a quad, or at least four straight lines that all run in one of two
    directions. The last covers frames drawn as runs of lines, such as a composite frame whose
    outline is split over two open paths; its corners are those of the parallelogram that spans
    the lines. Leaders have fewer lines, and a datum triangle runs in three directions.
    """
    if len(items) == 1 and items[0][0] == "re":
        rect = items[0][1]
        return [rect.tl, rect.tr, rect.br, rect.bl]
    if len(items) == 1 and items[0][0] == "qu":
        quad = items[0][1]
        return [quad.ul, quad.ur, quad.lr, quad.ll]
    if len(items) < 4 or any(item[0] != "l" for item in items):
        return None
    directions: list[pymupdf.Point] = []
    for _, start, end in items:
        step = end - start
        if abs(step) < 0.5:
            continue
        unit = step / abs(step)
        if not any(abs(unit.x * d.y - unit.y * d.x) < 0.05 for d in directions):
            directions.append(unit)
    if len(directions) != 2:
        return None
    u, v = directions
    det = u.x * v.y - u.y * v.x
    # each end point in the (u, v) basis, so the span along both directions is a parallelogram
    coords = [
        ((p.x * v.y - p.y * v.x) / det, (u.x * p.y - u.y * p.x) / det)
        for _, start, end in items
        for p in (start, end)
    ]
    s0, s1 = min(c[0] for c in coords), max(c[0] for c in coords)
    t0, t1 = min(c[1] for c in coords), max(c[1] for c in coords)
    return [u * s + v * t for s, t in ((s0, t0), (s1, t0), (s1, t1), (s0, t1))]


def _point(point: pymupdf.Point) -> Point:
    return point.x, point.y


def _rgb(colour: Sequence[float] | None) -> Colour | None:
    if not colour or len(colour) != 3:
        return None
    return tuple(round(c, 2) for c in colour)


def _area(frame: Frame) -> float:
    box = frame.box
    return (box.x1 - box.x0) * (box.y1 - box.y0)


def _union(rects: list[Rect]) -> Rect:
    box = rects[0]
    for rect in rects[1:]:
        box = box.union(rect)
    return box
