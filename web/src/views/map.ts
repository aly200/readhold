// Topic map: what this quest needs you to understand, in which order, and what you can already explain.
// Columns go from foundations (left) to what builds on them (right); lines show "needs".
// "Learn next" is the first concept whose foundations you can already explain.
import { api } from "../api";
import { removeItem } from "../trash";
import type { MapNode, Quest, TopicMap } from "../types";
import { append, clear, confirmBox, h, type ModalHandle, modal, toast } from "../util";

const STATUS: Record<MapNode["status"], { label: string; next: MapNode["status"] }> = {
  new: { label: "New to me", next: "shaky" },
  shaky: { label: "Shaky", next: "solid" },
  solid: { label: "I can explain it", next: "new" },
};

const COLUMN = ["Foundations", "Builds on those", "Then", "Then", "Then"];

export async function mapView(root: HTMLElement, questId: string): Promise<() => void> {
  const quest = await api.get<Quest>(`/api/quests/${questId}`);
  let map = await api.get<TopicMap>(`/api/quests/${questId}/map`);
  const page = h("section", { class: "topic-map" });
  root.append(page);
  const board = h("div", { class: "map-board" });
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "map-lines");
  svg.setAttribute("aria-hidden", "true");

  const set = (m: TopicMap) => {
    map = m;
    render();
  };
  const call = async (p: Promise<TopicMap>) => {
    try {
      set(await p);
    } catch (e) {
      toast((e as Error).message, "error", 5000);
    }
  };
  const byId = (id: string) => map.nodes.find((n) => n.id === id);

  const pickNeeds = (title: string, exclude: string[]): Promise<string[] | null> => {
    const chosen = new Set<string>();
    const opts = map.nodes.filter((n) => !exclude.includes(n.id));
    let handle: ModalHandle;
    return modal(
      title,
      h(
        "div",
        { class: "stack" },
        opts.length
          ? h("div", { class: "row wrap" }, opts.map((n) => {
              const b = h("button", { class: "chip", "aria-pressed": "false", onclick: () => {
                if (chosen.has(n.id)) chosen.delete(n.id);
                else chosen.add(n.id);
                b.classList.toggle("on", chosen.has(n.id));
                b.setAttribute("aria-pressed", String(chosen.has(n.id)));
              } }, n.name);
              return b;
            }))
          : h("p", { class: "muted" }, "Add other concepts first."),
        h("div", { class: "row end" }, h("button", { onclick: () => handle.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => handle.close([...chosen]) }, "Save")),
      ),
      { onOpen: (m) => (handle = m) },
    ).then((v) => (Array.isArray(v) ? (v as string[]) : null));
  };

  const refetch = () => call(api.get<TopicMap>(`/api/quests/${questId}/map`));
  // one "needs" link, with a ✕ that removes it (with Undo); the two concepts stay
  const needChip = (fromId: string, n: MapNode) => {
    const name = byId(fromId)?.name;
    const edge = map.edges.find((e) => e.from_id === fromId && e.to_id === n.id);
    if (!name) return null;
    return h("span", { class: "map-need" }, name, edge ? h("button", {
      class: "map-need-x", title: "Remove this link", "aria-label": `Remove the link: ${n.name} needs ${name}`,
      onclick: () => void removeItem("map_edge", edge.id, `Removed the link: “${n.name}” no longer needs “${name}”.`, { gone: () => void refetch(), back: () => void refetch() }),
    }, "✕") : null);
  };

  const nodeCard = (n: MapNode) => {
    const isNext = map.next?.id === n.id;
    const needs = n.needs.map((id) => needChip(id, n)).filter((x): x is HTMLSpanElement => !!x);
    return h(
      "div",
      { class: `map-node ${n.status} ${isNext ? "next" : ""} ${n.ready ? "" : "blocked"}`, "data-id": n.id },
      h(
        "div",
        { class: "map-node-head" },
        h("span", { class: "map-name" }, n.name),
        h("button", { class: "btn small ghost", "aria-label": `Remove ${n.name}`, onclick: async () => (await confirmBox("Remove this concept?", n.name, "Remove")) && call(api.del(`/api/map-nodes/${n.id}`)) }, "✕"),
      ),
      h("button", { class: `status-chip ${n.status}`, title: "Click to change", onclick: () => call(api.patch(`/api/map-nodes/${n.id}`, { status: STATUS[n.status].next })) }, n.status === "solid" ? "✓ " : "", STATUS[n.status].label),
      needs.length ? h("div", { class: "muted small map-needs" }, "Needs: ", needs) : null,
      h("button", { class: "link small", onclick: async () => {
        const picked = await pickNeeds(`What does “${n.name}” build on?`, [n.id, ...n.needs]);
        if (!picked) return;
        for (const from of picked) await call(api.post(`/api/quests/${questId}/map/edges`, { from_id: from, to_id: n.id }));
      } }, "+ Needs…"),
    );
  };

  const nextCard = () => {
    const n = map.next;
    if (!map.nodes.length) return null;
    if (!n) {
      return h("div", { class: "map-next done" }, h("div", { class: "kicker" }, "Learn next"), h("p", null, map.progress.solid === map.progress.total ? "You can explain every concept on this map. Teach the goal's questions back to check." : "Every open concept is waiting on a foundation. Mark the ones you can explain."));
    }
    return h(
      "div",
      { class: "map-next" },
      h("div", { class: "kicker" }, "Learn next"),
      h("p", { class: "map-next-name" }, n.name),
      h("p", { class: "muted small" }, n.needs.length ? "Its foundations are solid, so this is the right moment." : "It has no prerequisites: a good place to start."),
      h(
        "div",
        { class: "row wrap" },
        h("button", { class: "btn primary", onclick: async () => {
          await api.post(`/api/quests/${questId}/steps`, { title: `Learn: ${n.name}`, low: `Read one explanation of ${n.name}`, high: `Explain ${n.name} aloud, then write it in 3 sentences`, minutes: 20 });
          toast("Added as a step in your goal.", "ok");
        } }, "Make it a step"),
        h("button", { class: "btn", onclick: () => call(api.patch(`/api/map-nodes/${n.id}`, { status: "solid" })) }, "I can explain it"),
      ),
    );
  };

  const addForm = () => {
    const name = h("input", { type: "text", placeholder: "A concept this goal needs, e.g. softmax", "aria-label": "Concept" });
    let needs: string[] = [];
    const needsLabel = h("span", { class: "muted small" });
    const add = async () => {
      if (!name.value.trim()) return name.focus();
      await call(api.post(`/api/quests/${questId}/map/nodes`, { name: name.value.trim(), needs }));
      name.value = "";
      needs = [];
      needsLabel.textContent = "";
      name.focus();
    };
    name.addEventListener("keydown", (e) => e.key === "Enter" && add());
    return h(
      "div",
      { class: "map-add" },
      name,
      h("button", { class: "btn", onclick: async () => {
        const picked = await pickNeeds("What does it build on?", []);
        if (picked) {
          needs = picked;
          needsLabel.textContent = picked.length ? `needs ${picked.map((id) => byId(id)?.name).join(", ")}` : "";
        }
      } }, "Needs…"),
      needsLabel,
      h("button", { class: "btn primary", onclick: add }, "Add concept"),
      h("button", { class: "btn ghost", title: "Adds concepts from the documents this goal reads", onclick: async () => {
        const m = await api.post<TopicMap>(`/api/quests/${questId}/map/seed`);
        set(m);
        toast(m.added ? `Added ${m.added} concept${m.added > 1 ? "s" : ""} from your reading.` : "No new concepts found. Link a document to the goal first.", "info");
      } }, "Fill from my reading"),
    );
  };

  const drawLines = () => {
    clear(svg);
    const box = board.getBoundingClientRect();
    svg.setAttribute("width", String(board.scrollWidth));
    svg.setAttribute("height", String(board.scrollHeight));
    for (const e of map.edges) {
      const a = board.querySelector<HTMLElement>(`[data-id="${e.from_id}"]`);
      const b = board.querySelector<HTMLElement>(`[data-id="${e.to_id}"]`);
      if (!a || !b) continue;
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      const x1 = ra.right - box.left + board.scrollLeft;
      const y1 = ra.top + ra.height / 2 - box.top;
      const x2 = rb.left - box.left + board.scrollLeft;
      const y2 = rb.top + rb.height / 2 - box.top;
      const mid = (x1 + x2) / 2;
      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`);
      const solid = byId(e.from_id)?.status === "solid";
      path.setAttribute("class", solid ? "solid" : "");
      svg.append(path);
    }
  };

  const render = () => {
    clear(page);
    clear(board);
    const cols = Math.max(1, ...map.nodes.map((n) => n.depth + 1));
    for (let d = 0; d < cols; d++) {
      const nodes = map.nodes.filter((n) => n.depth === d);
      board.append(h("div", { class: "map-col" }, h("div", { class: "map-col-head kicker" }, COLUMN[Math.min(d, COLUMN.length - 1)]), nodes.map(nodeCard)));
    }
    board.append(svg);
    const pct = map.progress.total ? Math.round((map.progress.solid / map.progress.total) * 100) : 0;
    append(page, [
      h("div", { class: "isle page-head" },
      h("div", { class: "quest-top" }, h("span", { class: "badge accent" }, "Topic map"), h("a", { class: "quest-edit", href: `#/quest/${questId}` }, "Back to the goal")),
      h("h1", { class: "quest-title" }, quest.title),
      h("p", { class: "muted" }, "List the concepts this goal needs and what each builds on. Then rate each one honestly: can you explain it without notes?"),
      map.nodes.length ? [h("div", { class: "meter", "aria-hidden": "true" }, h("span", { style: { width: `${pct}%` } })), h("p", { class: "muted small" }, `${map.progress.solid} of ${map.progress.total} concepts you can explain`)] : null),
      nextCard(),
      map.nodes.length ? h("div", { class: "isle map-wrap" }, board) : h("p", { class: "isle map-empty muted" }, "No concepts yet. Add the first one, or fill the map from the documents this goal reads."),
      addForm(),
    ]);
    requestAnimationFrame(drawLines);
  };

  const onResize = () => requestAnimationFrame(drawLines);
  window.addEventListener("resize", onResize);
  board.addEventListener("scroll", onResize);
  render();
  return () => window.removeEventListener("resize", onResize);
}
