import { useEffect, useMemo, useState } from "react";
import type { AgentApi } from "./api";
import {
  ROUTE_LABELS,
  type LayerVerdict,
  duration,
  layerLabel,
  percent,
  sentence,
  traceSteps,
} from "./describe";
import type { RequestTrace } from "./types";

interface Props {
  api: AgentApi;
  requestId: string;
  /** The item open on the screen; its steps are marked. */
  itemId: string;
  /** Changes whenever the request moves on, so the trace is fetched again. */
  version: string;
}

/** What the agent did for the request, step by step, with every router layer's verdict. */
export function TracePanel({ api, requestId, itemId, version }: Props) {
  const [trace, setTrace] = useState<RequestTrace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .trace(requestId)
      .then((found) => {
        if (!alive) return;
        setTrace(found);
        setError(null);
      })
      .catch((cause: Error) => alive && setError(cause.message));
    return () => {
      alive = false;
    };
  }, [api, requestId, version]);

  const steps = useMemo(() => (trace ? traceSteps(trace.events) : []), [trace]);
  // A request of many files has steps for each; until the person asks for them all, show the
  // steps of the open item and of the request as a whole.
  const [whole, setWhole] = useState(false);
  const several = new Set(steps.map((step) => step.item).filter(Boolean)).size > 1;
  const shown =
    several && !whole ? steps.filter((step) => step.item === null || step.item === itemId) : steps;

  return (
    <div className="trace">
      <p className="trace-lookup">
        The same trace in a terminal:
        <code>uv run resourcly request {requestId}</code>
      </p>
      {several && (
        <div className="trace-scope" role="group" aria-label="Steps shown">
          <button type="button" aria-pressed={!whole} onClick={() => setWhole(false)}>
            This item
          </button>
          <button type="button" aria-pressed={whole} onClick={() => setWhole(true)}>
            Whole request
          </button>
        </div>
      )}
      {error && <p className="item-error">{error}</p>}
      {trace && (
        <ol className="trace-steps">
          {shown.map(({ event, item, layers }, index) => (
            <li
              key={index}
              className={`trace-step${event.error ? " failed" : ""}${item === itemId ? " this" : ""}`}
            >
              <div className="trace-head">
                <span className="trace-name">
                  {event.step.startsWith("route.") ? "routing, not ended" : event.step}
                </span>
                {item && <span className="trace-item">{item}</span>}
                <span className="trace-time">{duration(event.duration_ms)}</span>
              </div>
              <div className="trace-called">called {event.called}</div>
              {event.error && <div className="trace-error">{event.error}</div>}
              {layers.length > 0 && (
                <ol className="layers" aria-label={`Router layers for ${item ?? "this item"}`}>
                  {layers.map((layer, position) => (
                    <Layer key={position} layer={layer} />
                  ))}
                </ol>
              )}
              <details>
                <summary>Input and output</summary>
                <pre>{JSON.stringify({ input: event.input, output: event.output }, null, 2)}</pre>
              </details>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** One router layer: whether it decided or passed the item on, how sure, and why. */
function Layer({ layer }: { layer: LayerVerdict }) {
  const sure = layer.confidence === null ? null : percent(layer.confidence);
  const outcome = layer.error ? "failed" : layer.decided ? "decided" : "passed";
  return (
    <li className={`layer ${outcome}`}>
      <div className="layer-head">
        <span className="layer-name">{layerLabel(layer.layer)}</span>
        <span className="layer-outcome">
          {layer.error ? (
            "Failed"
          ) : layer.decided && layer.route ? (
            <>
              Decided{" "}
              <span className={`route-tag ${layer.route}`}>{ROUTE_LABELS[layer.route]}</span>
            </>
          ) : (
            "Passed on"
          )}
        </span>
        {sure !== null && <span className="layer-sure">{sure}%</span>}
        <span className="trace-time">{duration(layer.duration_ms)}</span>
      </div>
      {layer.error ? (
        <div className="trace-error">{layer.error}</div>
      ) : (
        layer.reason && <p className="layer-why">{sentence(layer.reason)}</p>
      )}
    </li>
  );
}
