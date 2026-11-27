// Delete on everything (milestone 5.1 of docs/ai/PLAN.md, Phase 5). One call removes a record (a soft delete:
// it stays in the database, out of sight, out of stats and exports), and the toast's Undo restores it.
// The server knows each kind and what hangs on it (readhold/trash.py); the page only names the kind and the id.
import { api } from "./api";
import { toast } from "./util";

export type ItemKind = "card" | "habit" | "quest" | "map_edge" | "journal" | "letter" | "side_quest" | "checkin" | "focus" | "ai_result";

export interface Restored {
  ok: boolean;
  kind: ItemKind;
  id: string;
  entry?: { id: string; day: string; weather: string; body: string; prompts: { q: string; a: string }[] }; // a journal page
}

/** Delete one record, then offer Undo for a while. `gone` runs once it is deleted, `back` once Undo restored it.
 *  Resolves false when the server refused (the reason is shown). */
export async function removeItem(kind: ItemKind, id: string, message: string, after: { gone?: () => void; back?: (r: Restored) => void } = {}): Promise<boolean> {
  try {
    await api.del(`/api/items/${kind}/${id}`);
  } catch (e) {
    toast(`Not deleted: ${(e as Error).message}`, "error", 6000);
    return false;
  }
  after.gone?.();
  toast(message, "info", 8000, {
    label: "Undo",
    run: async () => {
      try {
        after.back?.(await api.post<Restored>(`/api/items/${kind}/${id}/restore`));
      } catch (e) {
        toast(`Could not undo: ${(e as Error).message}`, "error", 6000);
      }
    },
  });
  return true;
}
