// The "AI" block of the Settings page, and the status chip in the menu.
// The page never builds a prompt and never calls a model: it changes settings and asks the server to test them.
import { api } from "../api";
import { state } from "../state";
import type { Settings } from "../types";
import { clear, confirmBox, h, toast } from "../util";

interface AiStatus {
  mode: "off" | "local" | "cloud";
  cloud_provider: string;
  key_set: boolean; // only whether a key is saved; the key itself never comes back from the server
  logged: number;
  provider: string;
  model: string;
  ready: boolean;
  problem: string;
  warning: string;
  usage: { used: number; budget: number; state: "ok" | "warn" | "stop" } | null;
}

type TestResult = { ok: true; provider: string; model: string; latency_ms: number; warning: string } | { ok: false; code: string; message: string };

const MODE_LABEL: Record<string, string> = { off: "Off", local: "Local", cloud: "Cloud" };
const MODE_HINT: Record<string, string> = {
  off: "AI is off. Readhold connects to nothing.",
  local: "AI uses the model server you set in Settings.",
  cloud: "AI uses a cloud model with your own key. Text for an AI call leaves this computer.",
};
const CLOUD_DEFAULT: Record<string, string> = { anthropic: "claude-opus-5-5", openai: "" };
const CLOUD_SMALL_DEFAULT: Record<string, string> = { anthropic: "claude-haiku-5-5", openai: "" };

/** The chip in the menu: Off, Local or Cloud. It opens the AI block of Settings. */
export function aiChip(): HTMLElement {
  const mode = MODE_LABEL[state.settings.ai_mode] ? state.settings.ai_mode : "off";
  return h("a", { class: `ai-chip ai-${mode}`, href: "#/settings?g=set-ai", title: MODE_HINT[mode], "aria-label": `AI: ${MODE_LABEL[mode]}. ${MODE_HINT[mode]}` },
    h("span", { class: "ai-dot", "aria-hidden": "true" }), `AI: ${MODE_LABEL[mode]}`);
}

let lastTest: { cls: string; text: string } | null = null; // the last Test connection result, kept across redraws

export function aiSettingsBlock(): HTMLElement {
  lastTest = null;
  const block = h("div", { class: "isle set-block", id: "set-ai" }, h("h2", null, "AI assistant"), h("p", { class: "muted small" }, "Loading…"));
  // a link to "#/settings?g=set-ai" (the chip) lands here once the block has its full height
  void draw(block).then(() => location.hash.includes("g=set-ai") && block.scrollIntoView({ block: "start" }));
  return block;
}

async function draw(block: HTMLElement): Promise<void> {
  let status: AiStatus;
  try {
    status = await api.get<AiStatus>("/api/ai/status");
  } catch (e) {
    clear(block);
    block.append(h("h2", null, "AI assistant"), h("p", { class: "import-warning" }, `The AI settings could not be loaded: ${(e as Error).message}`));
    return;
  }
  const s = state.settings;
  const redraw = () => draw(block);
  /** save AI settings; the server checks them, and a refused value is put back */
  const change = async (patch: Partial<Settings>, wholePage = false) => {
    try {
      state.settings = await api.put<Settings>("/api/settings", patch);
    } catch (e) {
      toast((e as Error).message, "error", 7000);
    }
    if (wholePage) window.dispatchEvent(new HashChangeEvent("hashchange")); // the chip in the menu shows the new mode
    else await redraw();
  };
  const select = (value: string, options: [string, string][], onchange: (v: string) => void) => {
    const el = h("select", { onchange: (e: Event) => onchange((e.target as HTMLSelectElement).value) }, options.map(([v, l]) => h("option", { value: v }, l)));
    el.value = value;
    return el;
  };
  const text = (value: string, placeholder: string, onchange: (v: string) => void) =>
    h("input", { type: "text", value, placeholder, spellcheck: false, autocomplete: "off", onchange: (e: Event) => onchange((e.target as HTMLInputElement).value.trim()) });
  const num = (value: number, min: number, max: number, step: number, onchange: (v: number) => void) =>
    h("input", { type: "number", value, min, max, step, onchange: (e: Event) => onchange(Number((e.target as HTMLInputElement).value)) });
  const field = (label: string, control: HTMLElement) => h("label", { class: "field" }, h("span", null, label), control);

  // ---- the API key: typed here, sent once to the server, kept in the credential store. It is never shown again.
  const provider = s.ai_cloud_provider;
  const keyBox = h("input", { type: "password", placeholder: status.key_set ? "A key is saved. Type a new one to replace it." : "Paste your API key", autocomplete: "off", spellcheck: false, "aria-label": "API key" });
  const saveKey = async () => {
    const key = keyBox.value.trim();
    if (!key) return;
    try {
      await api.put("/api/ai/key", { provider, key });
      toast("Key saved in the credential store of this computer.", "ok");
    } catch (e) {
      toast((e as Error).message, "error", 7000);
    }
    keyBox.value = "";
    await redraw();
  };
  const clearKey = async () => {
    if (!(await confirmBox("Clear the API key?", "The key is removed from the credential store of this computer. Cloud mode stops working until you save one again.", "Clear key"))) return;
    try {
      await api.del(`/api/ai/key?provider=${encodeURIComponent(provider)}`);
      toast("Key cleared.", "ok");
    } catch (e) {
      toast((e as Error).message, "error", 7000);
    }
    await redraw();
  };

  // ---- Test connection
  const result = h("p", { class: lastTest?.cls ?? "muted small ai-test-result", role: "status" }, lastTest?.text ?? "");
  const cancelBtn = h("button", { class: "btn small ghost", hidden: true }, "Cancel");
  const testBtn = h("button", { class: "btn" }, "Test connection");
  testBtn.addEventListener("click", async () => {
    const callId = crypto.randomUUID().replace(/-/g, "");
    testBtn.disabled = true;
    cancelBtn.hidden = false;
    cancelBtn.onclick = () => void api.post("/api/ai/cancel", { call_id: callId });
    result.className = "muted small ai-test-result";
    result.textContent = "Asking the model for one word…";
    try {
      const r = await api.post<TestResult>("/api/ai/test", { call_id: callId });
      lastTest = r.ok
        ? { cls: "small ai-test-result ok", text: `Connected: ${r.model} answered in ${(r.latency_ms / 1000).toFixed(1)} s.${r.warning ? ` ${r.warning}` : ""}` }
        : { cls: "small ai-test-result bad", text: r.message };
    } catch (e) {
      lastTest = { cls: "small ai-test-result bad", text: (e as Error).message };
    }
    await redraw(); // the result, and the day's token count and the log count with it
  });

  const usage = status.usage;
  const usageLine = usage
    ? usage.budget
      ? `Today: ${usage.used.toLocaleString()} of ${usage.budget.toLocaleString()} tokens used with this provider.${usage.state === "warn" ? " More than 80% is used." : usage.state === "stop" ? " The budget is used up: AI calls stop until tomorrow." : ""}`
      : `Today: ${usage.used.toLocaleString()} tokens used with this provider (no daily limit).`
    : "";

  clear(block);
  const parts: (HTMLElement | null)[] = [
    h("h2", null, "AI assistant"),
    h("p", { class: "muted small" }, "AI is off until you switch it on here, and Readhold works fully without it: every AI feature has a version without a model. With AI on, a feature asks a model only when you press its button."),
    // a short walkthrough for someone who has never run a model: open while AI is off, folded once it is set up
    h("details", { class: "ai-start", open: s.ai_mode === "off" || (s.ai_mode === "local" && !s.ai_local_model) },
      h("summary", null, "New to AI? Set it up in 5 minutes, on your own computer"),
      h("ol", null,
        h("li", null, h("strong", null, "Install Ollama"), ", a free app that runs AI models on your computer (from ollama.com). Nothing you read leaves this computer."),
        h("li", null, h("strong", null, "Download a model."), " In a terminal, type ", h("code", null, "ollama pull llama3.2"), " (about 2 GB). With 16 GB of memory or more, ", h("code", null, "qwen2.5:7b"), " gives better answers."),
        h("li", null, h("strong", null, "Connect it here."), " Just below, set AI to ", h("em", null, "Local model"), ", keep the server type ", h("em", null, "Ollama"), ", type ", h("code", null, "llama3.2"), " as the model, then press ", h("em", null, "Test connection"), " further down."),
        h("li", null, h("strong", null, "Try it."), " Select a passage in the reader and press Explain, or press 💬 in a note and ask the model to format it or write an idea.")),
      h("p", { class: "muted small" }, "Prefer a cloud model? Choose Cloud model, pick Anthropic or OpenAI and save your own API key. Every answer shows where it came from (Why did it say this?), and nothing changes until you press Use or Add.")),
    h("div", { class: "grid2" },
      field("AI", select(s.ai_mode, [["off", "Off (nothing connects anywhere)"], ["local", "Local model (a server on this computer)"], ["cloud", "Cloud model (your own API key)"]], (v) => change({ ai_mode: v as Settings["ai_mode"] }, true))),
      field("Stop a call after (seconds)", num(s.ai_timeout_s, 5, 600, 5, (v) => change({ ai_timeout_s: v }))),
    ),
    status.mode !== "off" && status.problem ? h("p", { class: "import-warning" }, status.problem) : null,

    h("h3", null, "Local model"),
    h("div", { class: "grid2" },
      field("Server type", select(s.ai_local_api, [["ollama", "Ollama"], ["openai", "OpenAI-compatible (llama.cpp, LM Studio)"]], (v) => change({ ai_local_api: v as Settings["ai_local_api"] }))),
      field("Endpoint", text(s.ai_local_endpoint, "http://localhost:11434", (v) => change({ ai_local_endpoint: v }))),
      field("Model", text(s.ai_local_model, "the name your server uses, like llama3.2", (v) => change({ ai_local_model: v }))),
      field("Small model for short tasks (optional)", text(s.ai_local_small_model, "empty = the model on the left", (v) => change({ ai_local_small_model: v }))),
      field("Daily token budget (0 = no limit)", num(s.ai_budget_local, 0, 1_000_000_000, 10000, (v) => change({ ai_budget_local: v }))),
    ),
    status.mode === "local" && status.warning ? h("p", { class: "import-warning" }, status.warning) : null,

    h("h3", null, "Cloud model"),
    h("div", { class: "grid2" },
      field("Provider", select(provider, [["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI"]], (v) => change({ ai_cloud_provider: v as Settings["ai_cloud_provider"] }))),
      field("Model", text(s.ai_cloud_model, CLOUD_DEFAULT[provider] ? `empty = ${CLOUD_DEFAULT[provider]}` : "the model's name", (v) => change({ ai_cloud_model: v }))),
      field("Small model for short tasks (optional)", text(s.ai_cloud_small_model, CLOUD_SMALL_DEFAULT[provider] ? `empty = ${CLOUD_SMALL_DEFAULT[provider]}` : "empty = the model on the left", (v) => change({ ai_cloud_small_model: v }))),
      field("Daily token budget (0 = no limit)", num(s.ai_budget_cloud, 0, 1_000_000_000, 10000, (v) => change({ ai_budget_cloud: v }))),
    ),
    h("div", { class: "field" },
      h("span", null, `API key for ${provider === "anthropic" ? "Anthropic" : "OpenAI"}: ${status.key_set ? "a key is saved" : "no key saved"}`),
      h("div", { class: "row wrap" }, keyBox, h("button", { class: "btn", onclick: saveKey }, "Save key"), status.key_set ? h("button", { class: "btn ghost", onclick: clearKey }, "Clear key") : null)),
    h("p", { class: "muted small" }, "The key is kept in the credential store of this computer (Windows Credential Manager, or the Keychain on a Mac), never in Readhold's database, files or log. It is not shown again after you save it."),
    h("p", { class: "ai-sends" },
      h("strong", null, "What cloud mode sends off this computer: "),
      "the text an AI call works on (for example the passage you selected, the section around it, or your question) and the instructions for the model. It goes to the provider you chose, over an encrypted connection, with your key. Nothing else is sent, and nothing is sent until an AI call is made. Local mode sends that text only to the endpoint above. With AI off, Readhold connects to nothing."),
    h("label", { class: "row" },
      h("input", { type: "checkbox", checked: s.ai_preview, onchange: (e: Event) => change({ ai_preview: (e.target as HTMLInputElement).checked }) }),
      h("span", null, "Show what will be sent before each cloud request, and send it only when I approve")),
    h("label", { class: "row" },
      h("input", { type: "checkbox", checked: s.ai_cloud_only_tagged, onchange: (e: Event) => change({ ai_cloud_only_tagged: (e.target as HTMLInputElement).checked }) }),
      h("span", null, "Send to the cloud model only documents and notes I tagged #cloud")),
    h("p", { class: "muted small" }, "Private items: a document or note tagged #private is never sent to a cloud model, and neither are your own notes that copy its sentences or name it (a local model still reads them). Tag a document in Organize, or write #private in a note. Secrets in the text (keys, passwords, e-mail addresses, phone numbers) are replaced by [redacted] before any cloud call."),

    h("div", { class: "row wrap" }, testBtn, cancelBtn),
    result,
    usageLine ? h("p", { class: "muted small" }, usageLine) : null,

    h("h3", null, "AI history"),
    h("p", { class: "muted small" }, `${status.logged} call${status.logged === 1 ? "" : "s"} in the log. Each call leaves one line: the task, the model, how long it took, the first 200 characters of what was sent and what came back, and where its sources were (never their text). Never a key.`),
    h("div", { class: "grid2" },
      field("Keep the AI log", select(String(s.ai_log_days), [["30", "30 days"], ["7", "7 days"], ["1", "1 day"]], (v) => change({ ai_log_days: Number(v) as Settings["ai_log_days"] })))),
    h("div", { class: "row wrap" },
      h("button", {
        class: "btn",
        onclick: async () => {
          if (!(await confirmBox("Clear AI history?", "The AI log is emptied, every recap, explanation, digest, answer, brainstorm and suggestion Readhold kept is deleted, the AI export files in the exports folder are deleted, and every AI call that is running stops. What you kept from a model is yours and stays: review cards, notes on a passage, Study notes and the ideas in your brainstorm sheets (delete them like any note or card). This cannot be undone (your daily backups still hold the data for up to 14 days, and full exports you made keep what they held).", "Clear"))) return;
          await api.del("/api/ai/log");
          toast("AI history cleared.", "ok");
          await redraw();
        },
      }, "Clear AI history")),
  ];
  block.append(...parts.filter((p): p is HTMLElement => p !== null));
}
