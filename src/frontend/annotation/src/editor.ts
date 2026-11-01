// The editing session for one drawing, kept in a reducer so every change goes through one place.
import type { GoldDocument, Issue, Value } from "./types";

export interface EditorState {
  /** The drawing that was opened; every request goes here, whatever `document.drawing` says. */
  drawing: string;
  document: GoldDocument;
  /** The document as last loaded or saved, to tell whether there are unsaved changes. */
  saved: string;
  selected: number | null;
  page: number;
  /** Issues from the last check or rejected save; their paths index into `document`. */
  issues: Issue[];
}

export type EditorAction =
  | { type: "select"; index: number | null }
  | { type: "step"; by: 1 | -1 }
  | { type: "page"; page: number }
  | { type: "editValue"; index: number; value: Value }
  | { type: "replace"; document: GoldDocument; select?: number | null }
  | { type: "issues"; issues: Issue[]; document: GoldDocument }
  | { type: "saved"; sent: GoldDocument; stored: GoldDocument };

export function openEditor(drawing: string, document: GoldDocument): EditorState {
  return {
    drawing,
    document,
    saved: JSON.stringify(document),
    selected: null,
    page: 1,
    issues: [],
  };
}

export function isDirty(state: EditorState): boolean {
  return JSON.stringify(state.document) !== state.saved;
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "select": {
      const value = action.index === null ? undefined : state.document.values[action.index];
      return { ...state, selected: action.index, page: value?.page ?? state.page };
    }
    case "step": {
      const count = state.document.values.length;
      if (count === 0) return state;
      const from = state.selected ?? (action.by > 0 ? -1 : count);
      const index = Math.min(count - 1, Math.max(0, from + action.by));
      return editorReducer(state, { type: "select", index });
    }
    case "page":
      return { ...state, page: action.page };
    case "editValue": {
      // A value moved to another page takes the view with it, so its box stays in sight.
      const moved = state.document.values[action.index]?.page !== action.value.page;
      return {
        ...state,
        page: moved ? action.value.page : state.page,
        document: {
          ...state.document,
          values: state.document.values.map((value, i) =>
            i === action.index ? action.value : value,
          ),
        },
      };
    }
    case "replace": {
      // Adding or removing records shifts the indexes issue paths point at; the next check refills them.
      const shifted =
        action.document.values.length !== state.document.values.length ||
        action.document.features.length !== state.document.features.length;
      const next = { ...state, document: action.document, issues: shifted ? [] : state.issues };
      return action.select === undefined
        ? next
        : editorReducer(next, { type: "select", index: action.select });
    }
    case "issues":
      // A check answers for the document it was sent; drop it if the person edited since.
      return action.document === state.document ? { ...state, issues: action.issues } : state;
    case "saved":
      // Take the server's copy unless the person kept typing while the save was in flight.
      return action.sent === state.document
        ? { ...state, document: action.stored, saved: JSON.stringify(action.stored), issues: [] }
        : { ...state, saved: JSON.stringify(action.sent) };
  }
}
