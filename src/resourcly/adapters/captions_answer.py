from resourcly.models import AnswerDraft, DraftFinding, PhotoEvidence


class CaptionsAnswerAdapter:
    """A model-free answerer: the closest figures' captions, each citing its figure.

    It reads nothing in the photo, says nothing to do, and always takes the figures as a match.
    It is the floor a model must beat, and lets tests and machines without the model answer.
    """

    called = "no model: the closest figures' captions"

    def answer(self, evidence: PhotoEvidence) -> AnswerDraft:
        if not evidence.figures:
            return AnswerDraft(False, "No report figure to compare the photo with.", [], [], "")
        best = evidence.figures[0]
        findings = [DraftFinding(figure.caption, figure.source) for figure in evidence.figures]
        answer = f"The closest report figure is {best.source}: {best.caption}"
        return AnswerDraft(True, answer, findings, [], answer)
