// Theme system: theme.json tokens → CSS variables. Time of day and energy shift the background only;
// the reading panel always stays solid and high-contrast.
import { ambience } from "./ambience";
import { sound } from "./sound";
import { state } from "./state";
import type { Theme } from "./types";

let todTimer: number | undefined;

export function currentTheme(): Theme {
  const find = (id: string) => state.themes.find((t) => t.id === id);
  return find(state.settings.theme) ?? find("clean") ?? state.themes[0]; // a missing theme falls back to the default
}

export function isDark(): boolean {
  const pref = state.settings.dark;
  if (pref === "dark") return true;
  if (pref === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(): void {
  const theme = currentTheme();
  if (!theme) return;
  const tokens = isDark() ? theme.tokens.dark : theme.tokens.light;
  const root = document.documentElement;
  for (const [k, v] of Object.entries(tokens)) root.style.setProperty(`--${k.replace(/_/g, "-")}`, v);
  root.dataset.mode = isDark() ? "dark" : "light";
  // a theme's whole look (ink lines, comic headings): set, or removed when the theme has none
  if (theme.look) root.dataset.look = theme.look;
  else delete root.dataset.look;
  if (theme.look && theme.look_variant) root.dataset.lookVariant = theme.look_variant;
  else delete root.dataset.lookVariant;
  root.dataset.energy = state.energy;
  root.dataset.progress = theme.progress;
  root.dataset.glass = state.settings.glass ?? "balanced";
  ambience.state.energy = state.energy;
  void ambience.apply(theme.id, theme.has_scene, tokens, isDark(), state.settings.intensity);
  sound.apply(theme.ambient_sound, Boolean(state.settings.sound), Number(state.settings.sound_volume ?? 0.35));
  applyTimeOfDay();
  clearInterval(todTimer);
  todTimer = window.setInterval(applyTimeOfDay, 5 * 60_000);
}

/** Dawn → day → dusk → night: a slow tint over the background (never over the text panel). */
export function applyTimeOfDay(): void {
  const hour = new Date().getHours() + new Date().getMinutes() / 60;
  let tint = "transparent";
  let alpha = 0;
  if (hour >= 5 && hour < 8) [tint, alpha] = ["255,190,120", 0.1];
  else if (hour >= 8 && hour < 17) [tint, alpha] = ["255,255,255", 0];
  else if (hour >= 17 && hour < 20) [tint, alpha] = ["255,150,80", 0.1];
  else [tint, alpha] = ["20,30,70", isDark() ? 0.12 : 0.08];
  document.documentElement.style.setProperty("--tod", tint === "transparent" ? "transparent" : `rgba(${tint},${alpha})`);
}

export function watchSystemTheme(): void {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
  window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", applyTheme);
}
