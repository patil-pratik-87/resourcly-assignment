import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AgentApi } from "./api";
import { elapsed, failureModeLabel, figureLabel, sectionLabel, statusLine } from "./describe";
import type { Citation, FigureMatch, PhotoAnswer, RequestItem } from "./types";

/** Figure thumbnails stay small; the larger view asks for a sharper image. */
const THUMB_SIDE = 320;
const LARGE_SIDE = 1600;

/** A figure to show larger: a close figure with its facts, or one a citation names alone. */
type Shown = { figure: string; match: FigureMatch | null; page: number | null };

/** Where a photo's answer has got: waiting for the answerer, or being answered. */
export function AnswerProgress({ item }: { item: RequestItem }) {
  return (
    <div className="read-progress">
      {item.status === "answering" && (
        <div className="read-bar working" role="progressbar" aria-label={`Answering ${item.name}`}>
          <span />
        </div>
      )}
      <div className="read-line">
        <span>{statusLine(item)}</span>
        {item.status === "answering" && item.started_at && (
          <span className="read-time">{elapsed(item.started_at)}</span>
        )}
      </div>
    </div>
  );
}

/**
 * What the agent says about a photo from the reports: the answer, the findings and actions with
 * their sources, and the closest report figures, each of which opens larger. When the gate finds
 * no figure close enough, it says only that the reports do not show it.
 */
export function PhotoAnswerView({
  api,
  name,
  answer,
}: {
  api: AgentApi;
  name: string;
  answer: PhotoAnswer;
}) {
  const [shown, setShown] = useState<Shown | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const ids = useId();

  function show(figure: string, page: number | null, from: HTMLElement) {
    opener.current = from;
    const match = answer.figures.find((candidate) => candidate.figure === figure) ?? null;
    setShown({ figure, match, page });
  }

  const close = useCallback(() => {
    setShown(null);
    opener.current?.focus();
  }, []);

  const cite = (citation: Citation) => <Cite citation={citation} onShow={show} />;

  if (answer.not_in_reports) {
    return (
      <section className="photo-answer gate" aria-label={`Answer about ${name}`}>
        <svg className="gate-icon" viewBox="0 0 20 20" aria-hidden>
          <circle cx="9" cy="9" r="5.5" />
          <path d="M13 13 L17 17 M6.5 9 H11.5" />
        </svg>
        <div>
          <h3>Not in the reports</h3>
          <p>{answer.answer}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="photo-answer" aria-label={`Answer about ${name}`}>
      {!answer.matched && <h3 className="answer-miss">No match in the reports</h3>}
      <p className="answer-text">{answer.answer}</p>

      {answer.findings.length > 0 && (
        <div className="answer-part">
          <h3 id={`${ids}-findings`}>From the reports</h3>
          <ul className="answer-list" aria-labelledby={`${ids}-findings`}>
            {answer.findings.map((finding, index) => (
              <li key={index}>
                <span>{finding.statement}</span>
                {cite(finding.citation)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.actions.length > 0 && (
        <div className="answer-part">
          <h3 id={`${ids}-actions`}>What to do</h3>
          <ul className="answer-list" aria-labelledby={`${ids}-actions`}>
            {answer.actions.map((action, index) => (
              <li key={index}>
                <span>{action.action}</span>
                {action.basis === "stated" && action.citation ? (
                  <span className="basis stated">Stated in {cite(action.citation)}</span>
                ) : (
                  <span
                    className="basis inferred"
                    title="The reports do not say this; it follows from the findings"
                  >
                    <span className="basis-tag">Inferred</span>
                    {action.citation && <> from {cite(action.citation)}</>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.figures.length > 0 && (
        <div className="answer-part">
          <h3 id={`${ids}-figures`}>Closest report figures</h3>
          <ul className="figure-strip" aria-labelledby={`${ids}-figures`}>
            {answer.figures.map((match) => (
              <li key={match.figure}>
                <button
                  type="button"
                  className="figure-thumb"
                  aria-label={`Open ${figureLabel(match.figure)} larger`}
                  onClick={(event) => show(match.figure, null, event.currentTarget)}
                >
                  <img src={api.figureUrl(match.figure, THUMB_SIDE)} alt="" />
                </button>
                <div className="figure-caption">
                  <div className="figure-name">
                    <strong>{figureLabel(match.figure)}</strong>
                    <Score score={match.score} />
                  </div>
                  <span className={`mode-tag ${modeClass(match.failure_mode)}`}>
                    {failureModeLabel(match.failure_mode)}
                  </span>
                  <span className="figure-section">{sectionLabel(match.section)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {shown && <FigureDialog api={api} shown={shown} onClose={close} />}
    </section>
  );
}

/** A source, as the answer cites it; a figure opens larger. */
function Cite({
  citation,
  onShow,
}: {
  citation: Citation;
  onShow: (figure: string, page: number, from: HTMLElement) => void;
}) {
  const figure = citation.figure;
  return figure ? (
    <button
      type="button"
      className="cite"
      title={`Report ${citation.report}, page ${citation.page}`}
      onClick={(event) => onShow(figure, citation.page, event.currentTarget)}
    >
      {citation.source}
    </button>
  ) : (
    <span className="cite" title={`Report ${citation.report}, page ${citation.page}`}>
      {citation.source}
    </span>
  );
}

function Score({ score }: { score?: number | null }) {
  if (score === null || score === undefined) return null;
  return (
    <span className="figure-score" title="How close the finder found the figure to the photo">
      {score.toFixed(2)}
    </span>
  );
}

/** A failure mode's tag colour: a defect, or an intact part shown for reference. */
function modeClass(mode: string): string {
  return mode === "reference_no_defect" ? "reference" : "defect";
}

/** A report figure shown larger, over the page, with what the report says it shows. */
function FigureDialog({
  api,
  shown,
  onClose,
}: {
  api: AgentApi;
  shown: Shown;
  onClose: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const label = figureLabel(shown.figure);
  const titleId = useId();
  const match = shown.match;

  useEffect(() => {
    closeButton.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "Tab") {
        // The close button is the dialog's one control, so focus stays on it.
        event.preventDefault();
        closeButton.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="figure-overlay" onClick={onClose}>
      <div
        className="figure-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="figure-dialog-head">
          <strong id={titleId}>{label}</strong>
          {match && (
            <span className={`mode-tag ${modeClass(match.failure_mode)}`}>
              {failureModeLabel(match.failure_mode)}
            </span>
          )}
          <span className="spacer" />
          <button ref={closeButton} type="button" className="quiet" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="figure-dialog-image">
          <img src={api.figureUrl(shown.figure, LARGE_SIDE)} alt={label} />
        </div>
        <dl className="figure-facts">
          <div>
            <dt>Report</dt>
            <dd>NTSB {match?.report ?? shown.figure.split("/")[0]}</dd>
          </div>
          {shown.page !== null && (
            <div>
              <dt>Page</dt>
              <dd>{shown.page}</dd>
            </div>
          )}
          {match && (
            <div>
              <dt>Section</dt>
              <dd>{sectionLabel(match.section)}</dd>
            </div>
          )}
          {match?.score !== null && match?.score !== undefined && (
            <div>
              <dt>Similarity</dt>
              <dd>{match.score.toFixed(2)}</dd>
            </div>
          )}
        </dl>
      </div>
    </div>,
    document.body,
  );
}
