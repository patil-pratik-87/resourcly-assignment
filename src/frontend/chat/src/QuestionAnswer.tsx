import { useId, useState } from "react";
import type { AgentApi } from "./api";
import { boxStyle } from "./bbox";
import type { Cited, QuestionAnswer } from "./types";

/** The answer's pages render small, like the card's page: enough to find the boxes. */
const PAGE_DPI = 96;

/** The values an answer shows: the cited one, or the candidates, in their order. */
export function shownValues(answer: QuestionAnswer): Cited[] {
  return [...answer.citations, ...answer.candidates].filter((cited) => cited.kind === "value");
}

/**
 * The answer to the person's question. A drawing's answer is its value, cut from the page;
 * candidates are numbered as their boxes on the page are, and a tap asks about that one. A text
 * answer lists each statement with the report page it comes from. `onPick` is left out where a
 * tap cannot ask again; `withPage` draws the values' page here, for a card that has none.
 */
export function QuestionAnswerView({
  api,
  answer,
  onPick,
  withPage = false,
}: {
  api: AgentApi;
  answer: QuestionAnswer;
  onPick?: (cited: Cited) => void;
  withPage?: boolean;
}) {
  const ids = useId();
  const lines = answer.reply.split("\n");
  const lead = lines[0] ?? "";
  const values = shownValues(answer);
  const [cited] = answer.citations;
  return (
    <section className="qa-answer" aria-labelledby={`${ids}-title`}>
      <header className="qa-head">
        <h3 id={`${ids}-title`}>Answer to your question</h3>
        {answer.picture && (
          <span className="qa-flag" title="The boxes of a picture are not exact">
            Read from a picture
          </span>
        )}
        {answer.checked && answer.outcome !== "none" && (
          <span className="qa-flag checked" title={checkedTitle(answer)}>
            {answer.route === "text" ? "Checked against the reports" : "Checked against the JSON"}
          </span>
        )}
      </header>

      {answer.route !== "text" && answer.outcome === "answer" && cited && (
        <ValueAnswer api={api} cited={cited} named={withPage} />
      )}

      {answer.route !== "text" && answer.outcome !== "answer" && (
        <>
          <p className={`qa-lead${answer.outcome === "none" ? " none" : ""}`}>{lead}</p>
          {values.length > 0 && (
            <ol className="qa-candidates" aria-label={candidatesLabel(answer)}>
              {values.map((value, index) => (
                <li key={`${value.item_id}/${value.ref}`}>
                  <Candidate
                    api={api}
                    cited={value}
                    number={index + 1}
                    named={withPage}
                    onPick={onPick && (() => onPick(value))}
                  />
                </li>
              ))}
            </ol>
          )}
        </>
      )}

      {answer.route === "text" && <TextAnswer answer={answer} lead={lead} />}

      {withPage && values.length > 0 && !answer.picture && (
        <AnswerPages api={api} values={values} numbered={answer.outcome !== "answer"} />
      )}
    </section>
  );
}

function checkedTitle(answer: QuestionAnswer): string {
  return answer.route === "text"
    ? "Each statement cites a report page the answer was shown"
    : "The values are printed from the drawing's JSON, not from the model's words";
}

function candidatesLabel(answer: QuestionAnswer): string {
  return answer.outcome === "none" ? "Every frame on the drawing" : "Candidates";
}

/** The one value that answers, with its crop, where it is, and what it means. */
function ValueAnswer({ api, cited, named }: { api: AgentApi; cited: Cited; named: boolean }) {
  return (
    <div className="qa-value">
      <Crop api={api} cited={cited} />
      <div className="qa-value-text">
        <code className="qa-raw">{cited.quote}</code>
        {cited.said && <p>{cited.said}</p>}
        <ValueChip cited={cited} named={named} />
      </div>
    </div>
  );
}

/** A candidate: its number on the page, its crop and text; a button when a tap can ask again. */
function Candidate({
  api,
  cited,
  number,
  named,
  onPick,
}: {
  api: AgentApi;
  cited: Cited;
  number: number;
  named: boolean;
  onPick?: () => void;
}) {
  const body = (
    <>
      <span className="qa-number" aria-hidden>
        {number}
      </span>
      <Crop api={api} cited={cited} />
      <code className="qa-raw">{cited.quote}</code>
      <ValueChip cited={cited} named={named} />
    </>
  );
  return onPick ? (
    <button
      type="button"
      className="qa-candidate"
      aria-label={`${number}: ${cited.quote}, ${cited.ref}. Ask about this one`}
      onClick={onPick}
    >
      {body}
    </button>
  ) : (
    <div className="qa-candidate">{body}</div>
  );
}

/** Where a value is: its id and page, and its file when the card is not the file's own. */
function ValueChip({ cited, named }: { cited: Cited; named: boolean }) {
  return (
    <span className="qa-where">
      <span className="cite" title={`Value ${cited.ref} of ${cited.item_id}, page ${cited.page}`}>
        {cited.ref}
        {cited.page ? ` · p${cited.page}` : ""}
      </span>
      {named && cited.item_id && <span className="qa-file">{cited.item_id}</span>}
    </span>
  );
}

/** A value cut from its page; a value read from a picture has no box to cut. */
function Crop({ api, cited }: { api: AgentApi; cited: Cited }) {
  if (!cited.bbox || !cited.request_id || !cited.item_id) return null;
  return (
    <span className="qa-crop">
      <img src={api.cropUrl(cited.request_id, cited.item_id, cited.ref)} alt="" />
    </span>
  );
}

/** A text answer: the answer, then each statement with the page it comes from. */
function TextAnswer({ answer, lead }: { answer: QuestionAnswer; lead: string }) {
  if (answer.outcome === "none") return <p className="qa-lead none">{lead}</p>;
  return (
    <>
      <p className="answer-text">{lead}</p>
      <ul className="answer-list">
        {answer.citations.map((cited, index) => (
          <Statement key={index} cited={cited} />
        ))}
      </ul>
    </>
  );
}

/** A statement and its page; the page opens the passage it comes from. */
function Statement({ cited }: { cited: Cited }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <li>
      <span>{cited.said}</span>
      <button
        type="button"
        className="cite"
        aria-expanded={open}
        aria-controls={id}
        title="Show the passage"
        onClick={() => setOpen((shown) => !shown)}
      >
        {cited.ref}
      </button>
      {open && (
        <blockquote id={id} className="qa-passage">
          {cited.quote}
        </blockquote>
      )}
    </li>
  );
}

/** The pages of an answer's values, each value boxed, numbered when there are candidates. */
function AnswerPages({
  api,
  values,
  numbered,
}: {
  api: AgentApi;
  values: Cited[];
  numbered: boolean;
}) {
  const pages = new Map<string, { cited: Cited; number: number }[]>();
  values.forEach((cited, index) => {
    if (!cited.bbox || !cited.request_id || !cited.item_id || !cited.page) return;
    const key = `${cited.request_id}/${cited.item_id}/${cited.page}`;
    pages.set(key, [...(pages.get(key) ?? []), { cited, number: index + 1 }]);
  });
  return (
    <div className="qa-pages">
      {[...pages.entries()].map(([key, marks]) => {
        const first = marks[0]!.cited;
        return (
          <div key={key} className="qa-page">
            <span className="sheet-page">
              <img
                src={api.pageUrl(first.request_id!, first.item_id!, first.page!, PAGE_DPI)}
                alt=""
              />
              <span className="sheet-marks">
                {marks.map(({ cited, number }) => (
                  <AnswerMark key={number} cited={cited} number={numbered ? number : null} />
                ))}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** A value of the answer boxed on its page, with its number when it is a candidate. */
export function AnswerMark({ cited, number }: { cited: Cited; number: number | null }) {
  return (
    <span className="mark answer" style={boxStyle(cited.bbox!)}>
      {number !== null && <span className="mark-number">{number}</span>}
    </span>
  );
}
