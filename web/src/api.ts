// The one small module that talks to the local Python server. A web version later only swaps this.

import { type Preview, previewDialog } from "./aipreview";

async function call<T>(method: string, path: string, body?: unknown, isForm = false, approve?: string, round = 0): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: approve ? { "X-AI-Approve": approve } : {} };
  if (body !== undefined) {
    if (isForm) init.body = body as FormData;
    else {
      init.body = JSON.stringify(body);
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
      // small writes finish even if the window is closing (the browser's 64 KB keepalive budget)
      if (method !== "GET" && init.body.length < 60_000) init.keepalive = true;
    }
  }
  const r = await fetch(path, init);
  if (r.status === 428) {
    // "Show what will be sent" (Settings → AI): nothing left this computer. Shown, then sent again only if you approve.
    const j = (await r.json().catch(() => ({}))) as { preview?: Preview };
    // a later call of the same request may need more of your items: it is shown and approved the same way
    if (j.preview && round >= 8) throw new Error("Stopped: this request kept asking to send more. Try again, or with fewer documents.");
    if (j.preview && !isForm && (await previewDialog(j.preview))) return call<T>(method, path, body, isForm, j.preview.token, round + 1);
    throw new Error("Not sent: you did not approve it.");
  }
  if (!r.ok) {
    let detail = `${r.status}`;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", p),
  post: <T>(p: string, b: unknown = {}) => call<T>("POST", p, b),
  patch: <T>(p: string, b: unknown) => call<T>("PATCH", p, b),
  put: <T>(p: string, b: unknown) => call<T>("PUT", p, b),
  del: <T>(p: string) => call<T>("DELETE", p),
  upload: <T>(p: string, form: FormData) => call<T>("POST", p, form, true),
};

/** Fire-and-forget writes that must not be lost: retried a few times, then logged. */
export function save(method: "post" | "patch" | "put" | "del", path: string, body?: unknown): Promise<unknown> {
  const attempt = (n: number): Promise<unknown> =>
    (method === "del" ? api.del(path) : api[method](path, body ?? {})).catch((e: Error) => {
      if (n < 3) return new Promise((res) => setTimeout(res, 400 * (n + 1))).then(() => attempt(n + 1));
      console.error("save failed", path, e);
      throw e;
    });
  return attempt(0);
}
