import { useCallback, useEffect, useState } from "react";
import { type AgentApi, createAgentApi } from "./api";
import { Chat } from "./Chat";
import { Requests } from "./Requests";
import { useRequests } from "./useRequests";
import type { AgentInfo } from "./types";

const browserApi = createAgentApi((url, init) => window.fetch(url, init));

/** Where the screen is: the chat, or the requests screen on one item of one request. */
export type Place =
  { screen: "chat" } | { screen: "requests"; requestId: string | null; itemId: string | null };

export function placeOf(pathname: string): Place {
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] !== "requests") return { screen: "chat" };
  return { screen: "requests", requestId: parts[1] ?? null, itemId: parts[2] ?? null };
}

export function pathOf(place: Place): string {
  if (place.screen === "chat") return "/chat";
  const parts = [place.requestId, place.itemId].filter((part): part is string => !!part);
  return ["/requests", ...parts.map(encodeURIComponent)].join("/");
}

/** The chat and the requests screen: one shell, one list of requests, polled while any works. */
export default function App({ api = browserApi }: { api?: AgentApi }) {
  const [place, setPlace] = useState<Place>(() => placeOf(window.location.pathname));
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const requests = useRequests(api);

  useEffect(() => {
    api
      .agent()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [api]);

  useEffect(() => {
    const onPop = () => setPlace(placeOf(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    document.title = place.screen === "chat" ? "Resourcly chat" : "Resourcly requests";
  }, [place.screen]);

  const go = useCallback((next: Place, replace = false) => {
    const path = pathOf(next);
    if (path !== window.location.pathname) {
      if (replace) window.history.replaceState(null, "", path);
      else window.history.pushState(null, "", path);
    }
    setPlace(next);
  }, []);

  const working = requests.requests.filter((record) => record.status === "working").length;
  const link = (next: Place) => ({
    href: pathOf(next),
    onClick: (event: React.MouseEvent) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      go(next);
    },
  });

  return (
    <div className="agent">
      <header className="topbar">
        <a className="brand" {...link({ screen: "chat" })}>
          <span className="brand-mark" aria-hidden />
          Resourcly
        </a>
        <nav className="screens" aria-label="Screens">
          <a
            {...link({ screen: "chat" })}
            aria-current={place.screen === "chat" ? "page" : undefined}
          >
            Chat
          </a>
          <a
            {...link({ screen: "requests", requestId: null, itemId: null })}
            aria-current={place.screen === "requests" ? "page" : undefined}
          >
            Requests
            {working > 0 && (
              <span className="screens-count" aria-label={`${working} working`}>
                {working}
              </span>
            )}
          </a>
        </nav>
        <div className="spacer" />
        {info && (
          <dl className="versions" aria-label="Agent versions">
            <div>
              <dt>Router</dt>
              <dd>{info.router}</dd>
            </div>
            <div>
              <dt>Reader</dt>
              <dd>{info.reader}</dd>
            </div>
            {info.answer && (
              <div>
                <dt>Answer</dt>
                <dd>{info.answer}</dd>
              </div>
            )}
          </dl>
        )}
      </header>
      {requests.error && (
        <div className="banner" role="alert">
          {requests.error}
        </div>
      )}
      {place.screen === "chat" ? (
        <Chat
          api={api}
          requests={requests.requests}
          loaded={requests.loaded}
          onSend={requests.send}
          onOpen={(requestId, itemId) => go({ screen: "requests", requestId, itemId })}
          info={info}
        />
      ) : (
        <Requests
          api={api}
          requests={requests.requests}
          loaded={requests.loaded}
          requestId={place.requestId}
          itemId={place.itemId}
          onLookup={requests.lookup}
          onOpen={(requestId, itemId, replace) =>
            go({ screen: "requests", requestId, itemId }, replace)
          }
          onChat={() => go({ screen: "chat" })}
        />
      )}
    </div>
  );
}
