import { useCallback, useEffect, useMemo, useState } from "react";
import type { AgentApi, SendOptions } from "./api";
import type { RequestRecord } from "./types";

/** How often to ask for the requests while one is still working. */
export const POLL_MS = 900;

/**
 * The latest requests, newest first, polled while any of them is still working so the chat and
 * the requests screen show each item as it goes. A request looked up by its id stays in the list
 * even when it is older than the latest ones the API lists.
 */
export function useRequests(api: AgentApi) {
  const [listed, setListed] = useState<RequestRecord[]>([]);
  const [lookedUp, setLookedUp] = useState<RequestRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Each tick asks the API again.
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .requests()
      .then((found) => {
        if (!alive) return;
        setListed(found);
        setError(null);
      })
      .catch((cause: Error) => alive && setError(`Could not load the requests: ${cause.message}.`))
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [api, tick]);

  const requests = useMemo(() => {
    const ids = new Set(listed.map((record) => record.request_id));
    return [...listed, ...lookedUp.filter((record) => !ids.has(record.request_id))];
  }, [listed, lookedUp]);

  const working = requests.some((record) => record.status === "working");
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => setTick((count) => count + 1), POLL_MS);
    return () => clearInterval(timer);
  }, [working]);

  /** Send one message; its request shows at once and then updates as the agent works. */
  const send = useCallback(
    async (text: string, files: File[], options?: SendOptions) => {
      const record = await api.send(text, files, options);
      setListed((current) => [
        record,
        ...current.filter((other) => other.request_id !== record.request_id),
      ]);
      return record;
    },
    [api],
  );

  /** Fetch one request by its id and keep it; throws the API's reason when there is none. */
  const lookup = useCallback(
    async (requestId: string) => {
      const record = await api.request(requestId);
      setLookedUp((current) => [
        ...current.filter((other) => other.request_id !== record.request_id),
        record,
      ]);
      return record;
    },
    [api],
  );

  return { requests, loaded, error, send, lookup };
}
