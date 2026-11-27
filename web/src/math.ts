// Math in document text. Importers store math as LaTeX between \( … \) (inline) and \[ … \] (display).
// Rendering uses the bundled KaTeX: katex.render() builds DOM nodes itself (no innerHTML), and `trust`
// stays off, so commands like \href, \url or \htmlData are refused. If LaTeX can't be rendered, the
// source is shown as plain text instead — reading never breaks on a formula.
import katex from "katex";

const MATH = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g;
const DISPLAY_EQ = /^\s*\\\[([\s\S]+?)\\\]\s*(\([^()]{1,12}\))?\s*$/;

// Macros papers use that KaTeX doesn't define itself. (Never redefine KaTeX's own — \R, \E, \bm,
// \coloneqq… — it makes expansion loop.)
const MACROS: Record<string, string> = {
  "\\mathbbm": "\\mathbb{#1}",
  "\\argmax": "\\operatorname*{arg\\,max}",
  "\\argmin": "\\operatorname*{arg\\,min}",
};

const cache = new Map<string, HTMLElement>();

export const hasMath = (text: string): boolean => text.includes("\\(") || text.includes("\\[");

/** One formula as a DOM element (cached; each call returns a fresh copy). */
export function mathEl(tex: string, display: boolean): HTMLElement {
  const key = (display ? "D" : "I") + tex;
  const hit = cache.get(key);
  if (hit) return hit.cloneNode(true) as HTMLElement;
  const el = document.createElement(display ? "div" : "span");
  el.className = display ? "math math-display" : "math";
  try {
    katex.render(tex, el, {
      displayMode: display,
      throwOnError: true,
      trust: false,
      strict: "ignore",
      output: "htmlAndMathml", // MathML inside is what screen readers read
      macros: { ...MACROS },
      maxExpand: 500,
      maxSize: 20,
    });
  } catch {
    el.textContent = tex;
    el.classList.add("math-raw");
    el.title = "Shown as LaTeX (this formula could not be drawn)";
  }
  if (cache.size > 3000) cache.clear();
  cache.set(key, el.cloneNode(true) as HTMLElement);
  return el;
}

/** Text that may contain math → nodes. Plain parts stay text nodes (never HTML). */
export function mathText(text: string): Node[] {
  if (!hasMath(text)) return [document.createTextNode(text)];
  const out: Node[] = [];
  let last = 0;
  for (const m of text.matchAll(MATH)) {
    if (m.index! > last) out.push(document.createTextNode(text.slice(last, m.index)));
    out.push(mathEl(m[1] ?? m[2], m[2] !== undefined));
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

/** A display equation paragraph ("\[ … \] (3)") → the formula plus its number, or null. */
export function displayEquation(text: string): { tex: string; tag: string } | null {
  const m = text.match(DISPLAY_EQ);
  return m ? { tex: m[1], tag: m[2] ?? "" } : null;
}

/** Words like /\S+/g, except that a formula stays one word even when its LaTeX contains spaces. */
export function wordsWithIndex(text: string): { word: string; index: number }[] {
  const out: { word: string; index: number }[] = [];
  let start = -1;
  let close = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (close) {
      if (text.startsWith(close, i)) {
        i += close.length - 1;
        close = "";
      }
      continue;
    }
    if (ch === "\\" && (text[i + 1] === "(" || text[i + 1] === "[")) {
      if (start < 0) start = i;
      close = text[i + 1] === "(" ? "\\)" : "\\]";
      i++;
      continue;
    }
    if (/\s/.test(ch)) {
      if (start >= 0) out.push({ word: text.slice(start, i), index: start });
      start = -1;
    } else if (start < 0) start = i;
  }
  if (start >= 0) out.push({ word: text.slice(start), index: start });
  return out;
}

export const words = (text: string): string[] => wordsWithIndex(text).map((w) => w.word);

/** Plain text for search, titles and tooltips: formulas keep their LaTeX, delimiters go. */
export const plainMath = (text: string): string => text.replace(MATH, (_, a, b) => (a ?? b).trim());

// ------------------------------------------------------------------ read-aloud
const SPOKEN: Record<string, string> = {
  frac: "", sqrt: "square root of", sum: "sum", prod: "product", int: "integral", infty: "infinity", partial: "partial",
  nabla: "nabla", cdot: "times", times: "times", div: "divided by", pm: "plus or minus", leq: "less than or equal to",
  le: "less than or equal to", geq: "greater than or equal to", ge: "greater than or equal to", neq: "not equal to",
  approx: "approximately", sim: "similar to", propto: "proportional to", in: "in", notin: "not in", subset: "subset of",
  to: "to", rightarrow: "goes to", leftarrow: "from", mapsto: "maps to", forall: "for all", exists: "there exists",
  log: "log", ln: "l n", exp: "exp", sin: "sine", cos: "cosine", tan: "tangent", max: "max", min: "min", arg: "arg",
  lim: "limit", det: "determinant", softmax: "softmax", top: "transpose", ldots: "and so on", cdots: "and so on",
  dots: "and so on", mid: "given", circ: "composed with", otimes: "tensor", oplus: "direct sum",
};
const GREEK = new Set(
  "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega".split(" "),
);

function speakTex(tex: string): string {
  let s = tex;
  for (let k = 0; k < 3; k++) {
    s = s
      .replace(/\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, " $1 over $2 ")
      .replace(/\\sqrt\s*\{([^{}]*)\}/g, " square root of $1 ")
      .replace(/\\(?:mathrm|mathbf|mathit|mathcal|mathbb|boldsymbol|bm|text|operatorname\*?|textrm|mathsf)\s*\{([^{}]*)\}/g, " $1 ");
  }
  s = s
    .replace(/\^\{?\s*2\s*\}?/g, " squared ")
    .replace(/\^\{?\s*(?:T|\\top|\\intercal)\s*\}?/g, " transpose ")
    .replace(/\^\{([^{}]*)\}|\^(\S)/g, " to the $1$2 ")
    .replace(/_\{([^{}]*)\}|_(\S)/g, " sub $1$2 ")
    .replace(/\\([a-zA-Z]+)/g, (_, n: string) => ` ${SPOKEN[n] ?? (GREEK.has(n) ? n : "")} `)
    .replace(/=/g, " equals ")
    .replace(/\+/g, " plus ")
    .replace(/\s-\s/g, " minus ")
    .replace(/[<]/g, " less than ")
    .replace(/[>]/g, " greater than ")
    .replace(/[{}\\&$|]/g, " ");
  return s.replace(/\s+/g, " ").trim() || "formula";
}

/** What the voice says for one word: formulas are read in rough words instead of LaTeX. */
export const spoken = (word: string): string => (hasMath(word) ? word.replace(MATH, (_, a, b) => ` ${speakTex(a ?? b)} `).trim() : word);
