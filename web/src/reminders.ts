// Reminders: a task for today that has a time rings once at that time, while Readhold is open.
// It is a chime and a note in the corner with one button to start a focus timer on the task.
// Nothing runs when the app is closed, and nothing leaves this machine.
import { api } from "./api";
import { chime, timer } from "./timer";
import { toast } from "./util";

interface Timed {
  id: string;
  text: string;
  at: string; // "14:30"
  minutes: number;
}
const fired = new Set<string>();
let tasks: Timed[] = [];
let day = "";

async function refresh(): Promise<void> {
  try {
    const r = await api.get<{ today: string; tasks: Timed[] }>("/api/todos/timed");
    tasks = r.tasks;
    day = r.today;
  } catch {
    /* the next try is a minute away */
  }
}

function check(): void {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  for (const t of tasks) {
    const [hh, mm] = t.at.split(":").map(Number);
    const late = minutes - (hh * 60 + mm);
    const key = `${day}:${t.id}:${t.at}`;
    if (late < 0 || fired.has(key)) continue;
    fired.add(key);
    if (late > 10) continue; // opening the app in the evening does not ring for the morning
    chime();
    toast(`${t.at} · ${t.text}`, "info", 30_000, { label: `Focus ${t.minutes} min`, run: () => void timer.start({ kind: "focus", minutes: t.minutes, todo_id: t.id }) });
  }
}

export function mountReminders(): void {
  void refresh().then(check);
  window.setInterval(check, 20_000);
  window.setInterval(() => void refresh(), 60_000);
  window.addEventListener("hashchange", () => void refresh()); // a task you just changed is known at once
}
