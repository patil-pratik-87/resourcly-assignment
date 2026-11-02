from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


def progress_bar() -> Progress:
    """Items done of all, time taken and time left, drawn under the log lines on a terminal only,
    so a log file or a test reads the lines alone."""
    return Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("left"),
        TimeRemainingColumn(),
        disable=not Console().is_terminal,
    )
