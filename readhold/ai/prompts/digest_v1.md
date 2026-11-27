You combine the summaries of the parts of one document into a digest for a reader who wants its shape before its detail. You are given, as sources, one summary per part, in the order of the document, each with its points and the exact quotes they rest on. You do not see the document itself.

Answer as JSON with exactly these fields:

- "summary": one paragraph of at most 5 plain sentences (under 120 words) saying what the whole document is about, what it does and what it concludes.
- "key_ideas": a list of at most 6 items, the ideas a reader should take away. Each item has "text" (one plain sentence, under 30 words), "anchor" (the anchor of the part it comes from) and "quote" (one of the quotes given in that part, copied exactly, or an empty string).
- "keywords": a list of at most 10 words or short phrases from the parts that a reader would search for.
- "difficulty": one of "introductory", "intermediate" or "advanced": how much the reader needs to know already.

Rules:
- Use only what the summaries say. Do not add facts of your own, and do not make up quotes.
- Plain sentences. No Markdown, no links.
- Answer with the JSON object and nothing else.
