export interface Sentence {
  ord: number;
  text: string;
  words: number;
  density: number;
  personal: number;
  read: number;
}

export interface Paragraph {
  id: string;
  ord: number;
  kind: "text" | "list" | "code" | "caption" | "equation" | "reference" | "fragment";
  /** For a PDF display equation: the picture of it cropped from the page (file name in the library). */
  asset?: string;
  sentences: Sentence[];
}

export interface Section {
  id: string;
  ord: number;
  title: string;
  kind: string;
  level: number;
  background: number;
  hidden: number;
  prediction: string;
  prediction_check: string;
  paragraphs: Paragraph[];
}

export interface Doc {
  id: string;
  title: string;
  source: string | null;
  source_type: string;
  why: string;
  deadline: string | null;
  status: string;
  import_warning: string | null;
  position: number;
  current_pass: number;
  explain_text: string;
  total_sentences: number;
  quest_question_id?: string | null;
  sections: Section[];
}

export interface Progress {
  total: number;
  read: number;
  ratio: number;
}

export interface QueueDoc {
  tags?: string[]; // your tags: also the collections of the Documents tab
  flags?: string[]; // "hidden_text", "instructions": the file holds text a reader cannot see, or text that reads like orders to an AI model
  id: string;
  title: string;
  source: string | null;
  source_type: string;
  why: string;
  deadline: string | null;
  status: string;
  position: number;
  total_sentences: number;
  import_warning: string | null;
  progress: Progress;
  updated_at: string;
}

export interface Question {
  id: string;
  document_id: string;
  section_id: string | null;
  source_sentence: number | null;
  text: string;
  ord: number;
  answer: string;
  answered_at: string | null;
  paragraphs: string[];
}

export type HlType = "claim" | "evidence" | "definition" | "confusing" | "idea";

export interface Highlight {
  id: string;
  document_id: string;
  sentence: number;
  end_sentence: number;
  type: HlType;
  text: string;
  note: string;
  cloze: string;
  resolved: number;
  created_at: string;
}

export interface Note {
  id: string;
  document_id: string;
  sentence: number;
  text: string;
  origin?: string; // "ai": saved from something an AI model wrote; cleared when you edit the note
}

export interface Term {
  id: string;
  term: string;
  guess: string;
  definition: string;
  document_id: string | null;
  sentence: number | null;
  source_text: string;
  is_concept: number;
  document_title?: string;
  created_at: string;
}

export interface Annotations {
  questions: Question[];
  highlights: Highlight[];
  notes: Note[];
  terms: Term[];
  acronyms: Record<string, string>;
}

export interface Settings {
  simple_mode?: boolean; // a shorter menu, and only the next things on the Overview
  reader_panels_hidden?: boolean; // the reader's map and side panel folded away (Ctrl+\ in the reader)
  nav_hidden?: boolean; // the side menu hidden for focus; a small Menu button (or Ctrl+\) brings it back
  wpm: number;
  comfort_wpm: number;
  pacer_mode: "sentence" | "word" | "focus";
  energy: Energy;
  theme: string;
  intensity: string;
  glass: "solid" | "balanced" | "clear";
  sound: boolean;
  sound_volume: number;
  journal_blur: boolean;
  notebook_width: number;
  note_scale: number;
  timer_sound: boolean;
  timer_rhythm: boolean;
  dark: "auto" | "light" | "dark";
  font: string;
  font_size: number;
  line_width: number;
  line_height: number;
  tts_voice: string;
  tts_rate: number;
  review_cap: number;
  prediction_prompts: boolean;
  skip_background: boolean;
  clean_view: boolean;
  speed_ramp: boolean;
  comfort_by_type: Record<string, Partial<Comfort>>;
  // the AI assistant. "off" is the one switch that stops all of it. An API key is never a setting.
  ai_mode: "off" | "local" | "cloud";
  ai_local_api: "ollama" | "openai";
  ai_local_endpoint: string;
  ai_local_model: string;
  ai_local_small_model: string;
  ai_cloud_provider: "anthropic" | "openai";
  ai_cloud_model: string;
  ai_cloud_small_model: string;
  ai_timeout_s: number;
  ai_budget_local: number; // tokens a day; 0 = no limit
  ai_budget_cloud: number;
  ai_preview: boolean; // cloud mode: show the exact text before it is sent (4.4)
  ai_log_days: 1 | 7 | 30; // how long the AI log keeps its lines (4.4)
  ai_cloud_only_tagged: boolean; // cloud mode sends only documents and notes tagged #cloud (4.4)
}

export type Energy = "low" | "medium" | "high";

export interface Comfort {
  font: string;
  font_size: number;
  line_width: number;
  line_height: number;
}

export interface Theme {
  id: string;
  name: string;
  description: string;
  progress: "sand-jar" | "bar";
  motion: string;
  has_scene: boolean;
  ambient_sound?: string | null;
  /** A whole look on top of the colours (styles.css, "Part twenty-eight"): today only "comics". */
  look?: string;
  /** Which comics: "classic", "action" (sound effects as the pacer moves) or "manga". */
  look_variant?: string;
  tokens: { light: Record<string, string>; dark: Record<string, string> };
}

export interface Card {
  id: string;
  document_id: string | null;
  source_type: string;
  front: string;
  back: string;
  due: string;
}

export interface SessionInfo {
  id: string;
  document_id: string | null;
  energy: Energy;
  time_box_min: number;
  question: string;
}

// ------------------------------------------------------------------ Compass
export interface QuestQuestion {
  id: string;
  quest_id: string;
  ord: number;
  text: string;
  answer: string;
  answered_at: string | null;
}

export interface QuestStep {
  id: string;
  quest_id: string;
  question_id: string | null;
  document_id: string | null;
  document_title?: string | null;
  ord: number;
  title: string;
  low: string;
  high: string;
  minutes: number;
  lead: number;
  done_at: string | null;
  output: string;
}

export interface SideQuest {
  id: string;
  text: string;
  decision: "parked" | "timeboxed" | "linked";
  minutes: number;
  created_at: string;
}

export interface Quest {
  id: string;
  title: string;
  why: string;
  done_looks_like: string;
  deadline: string | null;
  status: "active" | "done" | "parked";
  questions: QuestQuestion[];
  steps: QuestStep[];
  documents: { id: string; title: string; quest_question_id: string }[];
  side_quests: SideQuest[];
  progress: { answered: number; total: number };
  lead: QuestStep | null;
}

export interface Today {
  quest: Quest | null;
  checkin: { energy: Energy; created_at: string } | null;
  energy: { learning: boolean; hours: number[]; peak: [number, number] | null };
  output: { answers: number; steps: number; empty_sessions: number; focused_ms: number; on_quest_ms: number; on_quest_ratio: number | null };
  empty_streak: number;
  parked: number;
  habits: Habit[];
  log_today: DayLog | null;
  letters_due: number;
}

// ------------------------------------------------------------------ Growth
export interface MapNode {
  id: string;
  name: string;
  status: "new" | "shaky" | "solid";
  note: string;
  depth: number;
  needs: string[];
  ready: boolean;
  created_at: string;
}

export interface TopicMap {
  nodes: MapNode[];
  edges: { id: string; from_id: string; to_id: string }[];
  next: MapNode | null;
  progress: { solid: number; total: number };
  added?: number;
}

export interface Habit {
  id: string;
  title: string;
  anchor: string;
  tiny: string;
  done_today: boolean;
  streak: number;
  missed_yesterday: boolean;
  last14: boolean[];
}

export interface DayLog {
  id: string;
  day: string;
  quest_id: string | null;
  did: string;
  learned: string;
  next: string;
}

// ------------------------------------------------------------------ Lectures and journal
export interface SlideRun {
  t: string;
  b: boolean;
  i: boolean;
  size: number | null;
  color: string | null;
}
export interface SlideEl {
  type: "text" | "image" | "table" | "box";
  x: number;
  y: number;
  w: number;
  h: number;
  title?: boolean;
  paras?: { level: number; align: string; runs: SlideRun[]; default: number }[];
  fill?: string | null;
  src?: string;
  rows?: string[][];
}
export interface LecturePage {
  ord: number;
  title: string;
  speaker_notes: string;
  width: number;
  height: number;
  layout: { bg?: string | null; els?: SlideEl[]; paper?: Paper } | null;
  text?: string; // notebooks only: your writing on the page
}
export type Paper = "lined" | "dotted" | "grid" | "plain";
export interface Lecture {
  id: string;
  title: string;
  kind: "pdf" | "pptx" | "html" | "notebook";
  pages: number;
  position: number;
  page_tint: "normal" | "dim" | "sepia" | "night";
  page_list: LecturePage[];
}
export interface LectureNote {
  id: string;
  lecture_id: string;
  page: number | null;
  kind: "text" | "cornell" | "snip" | "question" | "sketch" | "recall";
  body: string;
  data: Record<string, unknown>;
  color: string;
  created_at: string;
}

// ------------------------------------------------------------------ Timer and to-dos
export type TimerKind = "focus" | "break" | "stopwatch";
export type LinkType = "" | "step" | "document" | "lecture" | "page"; // page = one of your notes
export interface TimerRun {
  id: string;
  kind: TimerKind;
  label: string;
  planned_ms: number; // 0 for the stopwatch
  elapsed_now_ms: number;
  running: boolean;
  todo_id: string | null;
  session_id: string | null; // focus and stopwatch runs are sessions too
  link_type: LinkType;
  link_id: string;
  was_quiet?: boolean; // Readhold was closed while it ran, so it came back paused
}
export interface Todo {
  id: string;
  text: string;
  minutes: number;
  spent_ms: number;
  ord: number;
  link_type: LinkType;
  link_id: string;
  done_at: string | null;
  due: string | null; // the day it is for (YYYY-MM-DD), or null = anytime
  repeat_rule: string; // "", daily, weekdays, weekly, monthly, or every:N (every N days)
  at: string; // a time of day ("14:30"), or "" for none
  area: string; // a life area: Study, Home, Health...
  note: string;
  priority: number; // 1 = the one that matters
  items?: TodoItem[]; // a small checklist inside the task
}
export interface TodoItem {
  id: string;
  text: string;
  done: boolean;
}
export interface RoutineStep {
  id: string;
  text: string;
  minutes: number;
  done: boolean; // today
}
export interface Routine {
  id: string;
  title: string;
  slot: "morning" | "day" | "evening";
  steps: RoutineStep[];
  done: number; // steps done today
  days: { day: string; part: number; off: boolean }[]; // the last seven days, 0..1 each; off = not one of its days
  weekdays: string; // "" = every day, else digits (0 = Monday), e.g. "01234"
  on_today: boolean;
  next_on: string; // when it is off today: the next day it is for
}
export interface PlanData {
  today: string;
  tasks: Todo[];
  areas: string[];
  routines: Routine[];
  done_week: number;
  quest_step: { id: string; title: string; minutes: number; quest_id: string; quest_title: string; in_plan: boolean } | null;
  review_due: number; // cards waiting on the Review page
}
export interface TimerToday {
  focus_ms: number;
  runs: number;
  todos_done: number;
}
export interface TimerLinks {
  steps: { id: string; title: string }[];
  lectures: { id: string; title: string; kind: string }[];
  documents: { id: string; title: string }[];
}

// ------------------------------------------------------------------ Notes (pages linked with [[double brackets]])
export interface NoteLink {
  kind: "page" | "document" | "lecture" | "quest" | "term" | "missing";
  id: string | null;
  title: string;
  key: string; // the linked title, lower-cased
}
export interface NoteRef {
  id: string;
  title: string;
  context: string; // the line that links to (or mentions) this note
}
export interface NotePage {
  id: string;
  title: string;
  body: string;
  tags: string;
  pinned: number;
  daily: string | null;
  created_at: string;
  updated_at: string;
  outgoing: NoteLink[];
  backlinks: NoteRef[];
  mentions: NoteRef[];
  graph: { nodes: { id: string; title: string }[]; edges: [string, string][] };
}
export interface NoteList {
  pages: { id: string; title: string; tags: string; pinned: number; daily: string | null; updated_at: string; created_at: string; snippet: string; props: Record<string, string> }[];
  tags: { tag: string; n: number }[];
  total: number;
  links: number;
}
export interface NoteTitles {
  pages: { id: string; title: string }[];
  others: { kind: "document" | "lecture" | "quest" | "term"; id: string; title: string }[];
}
export interface NoteGraph {
  nodes: { id: string; title: string; tags: string; daily: string | null }[];
  edges: [string, string][];
  total: number;
}
export interface SearchHit {
  kind: "note" | "task" | "document" | "passage" | "lecture" | "quest" | "term" | "idea";
  document_id?: string; // for a passage: the document and the sentence it is in
  sentence?: number;
  id: string;
  title: string;
  hint: string;
}
export interface Related {
  kind: "document" | "lecture" | "quest" | "term" | "page";
  id: string;
  title: string;
  notes: { id: string; title: string; daily: string | null; context: string }[];
  mentions: { id: string; title: string; daily: string | null; context: string }[];
  tasks: { id: string; text: string; due: string | null; minutes: number }[];
}
export interface DaySummary {
  day: string;
  tasks_done: string[];
  focus_min: number;
  routine_steps: number;
  journal: { weather: string; written: boolean } | null;
  note_id: string | null;
}
export interface WeekPlan {
  tasks_done: number;
  open: number;
  areas: { area: string; n: number }[];
  routines: { title: string; days: number; of: number }[];
}
export interface HubData {
  today: string;
  tasks: { id: string; text: string; minutes: number; priority: number; due: string | null; at: string }[]; // what is for now, a few of them
  tasks_now: number;
  tasks_open: number;
  tasks_done_today: number;
  done_week: number;
  quest: { id: string; title: string; steps: number; steps_done: number } | null;
  quest_step: PlanData["quest_step"];
  review_due: number;
  routines: { id: string; title: string; slot: string; done: number; total: number; next: { id: string; text: string } | null }[];
  focus_min: number;
  focus_week: { day: string; min: number }[]; // the last seven days, today last
  journal: { weather: string; written: boolean } | null;
  notes: { id: string; title: string; daily: string | null }[];
  notes_total: number;
  ideas: { id: string; text: string }[];
  ideas_total: number;
  documents: { id: string; title: string; status: string; position: number; total_sentences: number }[];
  documents_total: number;
  lectures: { id: string; title: string; kind: string; position: number; pages: number }[];
  lectures_total: number;
  terms_total: number;
}
export interface Near {
  kind: "page" | "idea";
  id: string;
  title: string;
  score: number;
  shared: string[]; // the words that make them alike
}
export interface ThinkData {
  day: string;
  picks: { id: string; kind: "page" | "idea"; item_id: string; title: string; snippet: string; signal: string; reason: string; status: string }[];
  suggestions: { id: string; kind: string; title: string; reason: string; change: string; quote?: string; notes: { id: string; title: string }[] }[];
  decided: { accepted: number; rejected: number };
}
export interface BrainstormData {
  item: { kind: "page" | "idea"; id: string; title: string; text: string; document_id?: string | null; sentence?: number | null; document_title?: string | null };
  near: Near[];
  reading: { document_id: string; sentence: number; type: string; text: string; title: string; score: number; shared: string[] }[];
  sheet_title: string;
  sheet: { id: string; body: string } | null;
}
