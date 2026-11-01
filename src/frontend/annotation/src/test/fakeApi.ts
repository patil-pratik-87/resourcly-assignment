import type { Api, SaveResult } from "../api";
import type { DrawingSummary, GoldDocument, Issue } from "../types";
import { ctc01 } from "./fixtures";

const summary = (drawing: string, values: number, page_count = 1): DrawingSummary => ({
  drawing,
  page_count,
  has_gold: values > 0,
  source: values > 0 ? "drawings" : null,
  values,
  approved: 0,
  issues: 0,
});

/**
 * The backend at its HTTP boundary: CTC-01 with gold, FTC-06 without. Tests replace
 * `check` or `save` to make the server report issues.
 */
export function fakeApi(
  overrides: Partial<Api> = {},
): Api & { saved: GoldDocument[]; savedTo: string[] } {
  const saved: GoldDocument[] = [];
  const savedTo: string[] = [];
  const documents: Record<string, GoldDocument> = {
    nist_ctc_01_asme1_rd: ctc01(),
    nist_ftc_06_asme1_rd: {
      drawing: "nist_ftc_06_asme1_rd",
      page_count: 3,
      title_block: {},
      features: [],
      values: [],
    },
  };
  return {
    saved,
    savedTo,
    drawings: async () => [
      summary("nist_ctc_01_asme1_rd", 17),
      summary("nist_ftc_06_asme1_rd", 0, 3),
    ],
    document: async (drawing) => structuredClone(documents[drawing]!),
    check: async (): Promise<Issue[]> => [],
    save: async (drawing, document): Promise<SaveResult> => {
      savedTo.push(drawing);
      saved.push(document);
      return { ok: true, document };
    },
    pageImage: (drawing, page) => `/pages/${drawing}/${page}.png`,
    ...overrides,
  };
}
