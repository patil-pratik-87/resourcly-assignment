import ctc01Json from "../../../../../tests/fixtures/gold/drawings/nist_ctc_01_asme1_rd.json";
import type { GoldDocument } from "../types";

/** A fresh copy of the complete CTC-01 gold fixture the backend tests use too. */
export function ctc01(): GoldDocument {
  return structuredClone(ctc01Json) as GoldDocument;
}
