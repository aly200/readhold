"""The stand-in model: a fake that answers every feature's prompt in-process, so the harness can be checked
without a model (in CI, for instance). It is not a model and its scores say nothing about one.

It plays a careful model: it quotes only sentences it was sent, copied exactly; it says "not found" when the
question's words are not in the sources; it searches once in the library loop, then answers. In Tidy it rewords with
your own words, but puts a verb before a task that has none (a word you did not write, which the score counts). In
Plan chat it drafts each thing your message lists, on the first day with room for it, even one you already have
(code leaves that out, and the score counts it). It knows a feature by words of its prompt (`readhold/ai/prompts/`),
the same way `tests/test_ai_citations.py` does.

`answer(body)` takes an Ollama /api/chat request body and returns the reply body. The port reaches it through
`Port.use_stand_in`, so every guard runs as with a real model and nothing connects anywhere.
"""
from __future__ import annotations

import json
import re
from collections import Counter

# (words of the prompt, feature): the first match wins, so the longer prompts' words come first
KNOWN = [
    ("help a reader with one of their notes", "notechat"),
    ("summarise one part", "digest_map"),
    ("combine the summaries", "digest"),
    ("organize their library", "organize"),
    ("tidy what they wrote", "tidy"),
    ("plan their tasks", "chat"),
    ("judge a list of ideas", "brainstorm_critic"),
    ("help a reader brainstorm", "brainstorm"),
    ("order in which to read", "plan"),
    ("help a reader study", "notes"),
    ("from their own library", "library"),
    ("question about one document", "ask"),
    ("You explain a passage", "explain"),
    ("pick up a document where they left off", "resume"),
]
SOURCE = re.compile(r'<source anchor="([^"]*)" trust="([^"]*)">\n(.*?)\n</source>', re.S)
QUESTION = re.compile(r"<question>\n(.*?)\n</question>", re.S)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
CURLY = re.compile(r"“([^”]{12,})”")
STOP = set("what which does with from that this have long much many should their there when where were into each about could would they them "
           "your before after need needs because more most some than then also only".split())
# Tidy and Plan chat: how the features write what you wrote into their sources (readhold/ai/tidy.py, chat.py)
TASK = re.compile(r"\(Task (\d+)\) (.*) \| (\d+) min \| day: .*")
STEP = re.compile(r"(?m)^\d+\. (.*) \((\d+) min\)$")
FREE = re.compile(r"(?m)^(\d{4}-\d{2}-\d{2}) \w+: (\d+) free of \d+ minutes$")
DAY_WORDS = ("today", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
VERBS = set("add ask bake book buy call check clean cook do drink email feed finish fix go look make meet mix pay plan practise read review "
            "revise send shape stretch study take walk write".split())


def feature_of(system: str, user: str) -> str:
    for words, name in KNOWN:
        if words in system:
            return name
    return "test" if "single word: ready" in user else ""


def _sources(user: str) -> list[tuple[str, str, str]]:
    return SOURCE.findall(user)


def _sentences(body: str) -> list[str]:
    """The sentences of a source, without the header lines a feature puts in brackets."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or (line.startswith("(") and line.endswith(")")):
            continue
        out += [s.strip() for s in SENTENCE.split(line) if s.strip()]
    return out


def _quote(body: str, min_words: int = 6) -> str:
    """A quote copied exactly from a source: a quote the source itself holds (a digest part), else its first full sentence."""
    found = CURLY.findall(body)
    if found:
        return found[0]
    sents = _sentences(body)
    for s in sents:
        if len(s.split()) >= min_words:
            return " ".join(s.split()[:24])
    return sents[0] if sents else ""


def _stem(word: str) -> str:
    return word[:5]


def _words(text: str) -> list[str]:
    """A question's own words: the longer ones and acronyms (GPU), as stems."""
    out = [w.lower() for w in re.findall(r"\b[A-Z]{2,}\b", text)]
    out += [_stem(w) for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP]
    return list(dict.fromkeys(out))


def _hits(sentence: str, stems: list[str]) -> int:
    low = sentence.lower()
    return sum(1 for s in stems if re.search(r"\b" + re.escape(s), low))


def _docs(srcs) -> list[tuple[str, str]]:
    """(anchor, text) of the sources that come from documents (an anchor "<id>:<sentence>")."""
    return [(a, b) for a, t, b in srcs if re.fullmatch(r"[0-9a-f]{32}:\d+", a)]


def _answer_from(srcs, question: str, most: int) -> tuple[bool, str, list[dict]]:
    stems = _words(question)
    text = " ".join(b for _, _, b in srcs).lower()
    if not stems or not all(re.search(r"\b" + re.escape(s), text) for s in stems):
        return False, "", []
    best: dict[str, tuple[int, str, str]] = {}  # per document: its sentence with most of the question's words
    for a, b in _docs(srcs):
        for s in _sentences(b):
            n = _hits(s, stems)
            doc = a.split(":")[0]
            if n and (doc not in best or n > best[doc][0]):
                best[doc] = (n, a, s)
    picked = sorted(best.values(), key=lambda x: -x[0])[:most]
    if not picked:
        return False, "", []
    cites = [{"anchor": a, "quote": s.rstrip(".")} for _, a, s in picked]
    return True, " ".join(s for _, _, s in picked), cites


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _tidy_task(number: int, was: str, minutes: int) -> dict | None:
    """One task reworded: stray marks gone, a day word moved to "day", a split at "and". None when it is already clear."""
    text = " ".join(re.sub(r"[!?]+|\s[-–]\s", " ", was).split())
    day = next((d for d in DAY_WORDS if re.search(rf"\b{d}\b", text, re.I)), "")
    if day:
        text = " ".join(re.sub(rf"\b(?:on |by )?{day}\b", " ", text, flags=re.I).split())
    if not text:
        return None
    if text.split()[0].lower() not in VERBS:
        text = "Plan " + text  # a task starts with a verb; this one you did not write
    text = _cap(text)
    if text == was and not day:
        return None
    parts = [_cap(p) for p in text.split(" and ")] if " and " in text else []
    return {"task": number, "text": text, "minutes": minutes, "day": day, "split": [{"text": p, "minutes": 0} for p in parts]}


def _tidy(system: str, srcs) -> dict:
    if "Kind: tasks" in system:
        tasks = [_tidy_task(int(m.group(1)), m.group(2), int(m.group(3))) for _, _, b in srcs if (m := TASK.fullmatch(b.strip()))]
        return {"tasks": [t for t in tasks if t]}
    body = srcs[0][2] if srcs else ""
    if "Kind: a note" in system:
        head, _, text = body.partition("\n")
        title = re.fullmatch(r"\(Your note: (.*)\)", head)
        lines = [f"- {_cap(s)}" for line in text.splitlines() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+([,;:.!?])", r"\1", line.strip())) if s]
        return {"body": (f"# {title.group(1)}\n\n" if title else "") + "\n".join(lines)}
    steps = []
    for text, minutes in STEP.findall(body):
        timed = re.search(r"\s*\bfor (\d+) minutes?\b", text)
        if timed:
            text, minutes = text[:timed.start()] + text[timed.end():], timed.group(1)
        steps.append({"text": _cap(" ".join(text.split())), "minutes": int(minutes)})
    return {"steps": steps}


def _chat(srcs, question: str) -> dict:
    """Each thing the message lists ("Plan my week: a, b, and c (40 min)") on the first day, not before the last
    draft's, whose free minutes it fits in; 30 minutes unless the message says."""
    free = {d: int(f) for _, _, b in srcs for d, f in FREE.findall(b)}
    days = sorted(free)
    listed = question.rsplit(":", 1)[-1]
    tasks, at, left_out = [], 0, 0
    for part in re.split(r",\s*(?:and\s+|then\s+)?|;\s*|\s+then\s+", listed):
        m = re.search(r"\s*\((\d+) min\)", part)
        minutes = int(m.group(1)) if m else 30
        text = _cap(" ".join((part[:m.start()] + part[m.end():] if m else part).strip(" .").split()))
        if not text:
            continue
        k = next((i for i in range(at, len(days)) if free[days[i]] >= minutes), None)
        if k is None:
            left_out += 1
            continue
        free[days[k]] -= minutes
        at = k
        tasks.append({"text": text, "day": days[k], "minutes": minutes})
    reply = "Here is a plan that fits your free time." + (f" {left_out} of the things you listed fit on no day; tell me what to drop." if left_out else "")
    return {"reply": reply, "tasks": tasks}


def _notechat(srcs, question: str) -> dict:
    """Asked to write (an idea, a story), new text to add; otherwise the note rewritten as a heading and a list,
    keeping every line (so your links and tags stay)."""
    body = srcs[0][2] if srcs else ""
    head, _, text = body.partition("\n")
    title = re.fullmatch(r"\(The note you are in: (.*)\)", head)
    name = title.group(1) if title else "this"
    if re.search(r"\b(write|idea|story)\b", question, re.I):
        return {"reply": "Here is an idea you could build on.", "action": "add",
                "text": f"## Story idea\n\nA short story set on the day of {name.lower()}: what if the plan goes wrong at the first stop?"}
    lines = [f"- {_cap(s)}" for line in text.splitlines() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+([,;:.!?])", r"\1", line.strip())) if s]
    return {"reply": "I gave it a heading and a list.", "action": "replace", "text": f"# {name}\n\n" + "\n".join(lines)}


def _reply(name: str, system: str, user: str) -> dict | str:
    srcs = _sources(user)
    docs = _docs(srcs)
    q = QUESTION.search(user)
    question = q.group(1) if q else ""
    if name == "test":
        return "ready"
    if name == "resume":
        return {"recap": [{"text": "You read this part.", "anchor": a, "quote": _quote(b)} for a, b in docs[:2]],
                "point": "The section makes one main point.", "next": "Go on with the next paragraph."}
    if name == "explain":
        a, b = next(((a, b) for a, _, b in srcs if b.startswith("(The selected passage)")), docs[0] if docs else ("", ""))
        quote = _quote(b, 3)
        return {"explanation": f"In plain words: {quote}.", "terms": [], "feedback": "", "quote": quote}
    if name == "digest_map":
        sents = _sentences(docs[0][1]) if docs else []
        points = [{"text": "This part says so.", "quote": " ".join(s.split()[:24])} for s in sents if len(s.split()) >= 6][:2]
        return {"summary": sents[0] if sents else "A part.", "points": points, "keywords": []}
    if name == "digest":
        return {"summary": "The document in a few lines.", "difficulty": "intermediate", "keywords": [],
                "key_ideas": [{"text": "An idea the part makes.", "anchor": a, "quote": _quote(b)} for a, b in docs[:4] if _quote(b)]}
    if name == "ask":
        found, text, cites = _answer_from(srcs, question, 1)
        return {"found": found, "answer": text, "citations": cites}
    if name == "library":
        if "Step 1 of" in system:
            return {"action": "search", "keywords": " ".join(w for w in re.findall(r"[A-Za-z]{4,}", question) if w.lower() not in STOP)}
        found, text, cites = _answer_from(srcs, question, 2)
        return {"action": "answer", "found": found, "answer": text, "citations": cites}
    if name == "notes":
        cards = "Kind: notes" not in system
        return {"items": [{"text": "What does this passage say?" if cards else "A note on this passage.",
                           "answer": _quote(b) if cards else "", "anchor": a, "quote": _quote(b)} for a, b in docs[:4] if _quote(b)]}
    if name == "plan":
        left = []
        for a, _, b in srcs:
            m = re.match(r"\(Document (\d+): .*?\)\n\(Left to read: (\d+) words", b)
            if m:
                left.append((int(m.group(2)), int(m.group(1)), b))
        return {"order": [{"document": k, "difficulty": "medium", "reason": "Shorter, so it comes first.", "quote": _quote(b)}
                          for _, k, b in sorted(left)]}
    if name == "brainstorm":
        angle = re.search(r"Angle: (\w+)", system)
        how = {"connect": "Link this to another text:", "question": "Ask what would prove this wrong:", "apply": "Try this on a problem of your own:"}
        lead = how.get(angle.group(1) if angle else "", "Think about:")
        ideas = []
        for a, b in docs[:2]:
            quote = _quote(b, 4)
            ideas.append({"text": f"{lead} {quote.split(' ', 3)[-1]}", "sources": [{"anchor": a, "quote": quote}]})
        return {"ideas": ideas}
    if name == "brainstorm_critic":
        n = len(re.findall(r"(?m)^\d+\. ", user))
        return {"groups": [{"label": f"Idea {i + 1}", "ideas": [i], "best": i} for i in range(n)]}
    if name == "organize":
        listed = re.search(r"\(The tags you already use\)\n(.*?)\n\(Already on this document\)", user, re.S)
        known = [t.strip() for t in (listed.group(1) if listed else "").split(",") if t.strip() and t.strip() != "none yet"]
        text = " ".join(b for _, b in docs).lower()
        fit = [t for t in known if any(re.search(r"\b" + re.escape(_stem(p)), text) for p in t.split("-"))]
        common = Counter(w for w in re.findall(r"[a-z]{6,}", text) if w not in STOP).most_common(1)
        new = [common[0][0]] if common and common[0][0] not in fit else []
        quote = _quote(docs[0][1]) if docs else ""
        return {"tags": [{"tag": t, "quote": quote} for t in fit + new],
                "related": [{"document": 1, "reason": "It is about something close."}] if "(Other documents in your library, numbered)" in user else []}
    if name == "tidy":
        return _tidy(system, srcs)
    if name == "chat":
        return _chat(srcs, question)
    if name == "notechat":
        return _notechat(srcs, question)
    return {}


def answer(body: dict) -> dict:
    """The reply to one Ollama /api/chat request, with token counts the AI log can sum."""
    messages = body.get("messages") or []
    system = next((m["content"] for m in messages if m.get("role") == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    out = _reply(feature_of(system, user), system, user)
    content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return {"model": body.get("model", ""), "message": {"role": "assistant", "content": content}, "done": True,
            "prompt_eval_count": (len(system) + len(user)) // 4, "eval_count": max(1, len(content) // 4)}
