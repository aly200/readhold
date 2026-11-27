import { api } from "./api";
import type { Comfort, Energy, Settings, Theme } from "./types";

export const state = {
  settings: null as unknown as Settings,
  themes: [] as Theme[],
  energy: "medium" as Energy,
};

export async function loadState(): Promise<void> {
  const [settings, themes, amb] = await Promise.all([
    api.get<Settings>("/api/settings"),
    api.get<Theme[]>("/api/themes"),
    api.get<{ energy_today: Energy | null }>("/api/ambience").catch(() => ({ energy_today: null })),
  ]);
  state.settings = settings;
  state.themes = themes;
  state.energy = amb.energy_today ?? settings.energy; // today's check-in wins over the default
}

export async function saveSettings(patch: Partial<Settings>): Promise<void> {
  Object.assign(state.settings, patch);
  state.settings = await api.put<Settings>("/api/settings", patch);
}

export const FONTS: Record<string, { label: string; css: string }> = {
  atkinson: { label: "Atkinson Hyperlegible", css: '"Atkinson Hyperlegible", system-ui, sans-serif' },
  literata: { label: "Literata (serif)", css: 'Literata, Georgia, "Times New Roman", serif' },
  opendyslexic: { label: "OpenDyslexic", css: 'OpenDyslexic, "Comic Sans MS", sans-serif' },
  system: { label: "System sans", css: 'system-ui, "Segoe UI", sans-serif' },
  serif: { label: "System serif", css: 'Georgia, "Times New Roman", serif' },
};

export function comfortFor(sourceType: string): Comfort {
  const s = state.settings;
  const base: Comfort = { font: s.font, font_size: s.font_size, line_width: s.line_width, line_height: s.line_height };
  return { ...base, ...(s.comfort_by_type?.[sourceType] ?? {}) };
}

export function applyComfort(c: Comfort): void {
  const root = document.documentElement.style;
  root.setProperty("--read-font", (FONTS[c.font] ?? FONTS.atkinson).css);
  root.setProperty("--read-size", `${c.font_size}px`);
  root.setProperty("--read-width", `${c.line_width}ch`);
  root.setProperty("--read-leading", String(c.line_height));
}
