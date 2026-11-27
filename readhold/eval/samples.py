"""The fixed sample set of the evaluation: four short texts written for it (no one's copyright), the tags and
highlights put on them, writing that stands for your own (open tasks, a note, a routine: what Tidy and Plan chat
read), and the cases each feature is run on.

Nothing here is the user's: these texts are the only ones the evaluation sends to a model, local or cloud.
Change them only on purpose: scores are comparable between runs only on the same set (`VERSION` says which).
"""
from __future__ import annotations

VERSION = "3"  # 2: Tidy and Plan chat, with the tasks, note and routine they read; 3: the note chat (two requests)

ROUTER = """# Block Routing for Long Inputs

## Abstract

We describe a block router that lets a transformer read long inputs at a lower cost. The router splits the input into blocks of 256 tokens. The approach keeps quality close to full attention while using less memory.

## Method

Each block receives a relevance score from a small scoring network. The router keeps the four highest-scoring blocks for each query. Blocks that are not kept are summarised into a single memory vector.

## Results

On a long-document benchmark, the block router scored 64.1 against 63.5 for full attention. Memory use fell by 38% on inputs longer than 16,000 tokens. Speed gains were small on short inputs.

## Limits

The router can drop a block that matters when its score is low. We did not test inputs in languages other than English.
"""

SOIL = """# How Rain Moves Through Hill Soil

## Overview

This field note follows rainwater on a grassy hillside over one wet season. Most rain soaks into the top layer of soil within an hour. Water reaches the deeper clay layer only after two or three days.

## Measurements

We placed moisture sensors at three depths along the slope. The upper sensors filled first after every storm. On steep ground, part of the water ran along the surface instead of soaking in.

## What it means

Grass roots slow the water and help it soak into the hill. A bare slope loses more soil to runoff during heavy storms.
"""

BREAD = """# Slow Sourdough at Home

## Starter

A sourdough starter is a mix of flour and water that holds wild yeast. The slow fermentation gives the bread its sour taste. Feed the starter every day and keep it at room temperature. A lively starter doubles in size within six hours of feeding.

## Dough

Mix the flour, water, salt and starter into a shaggy dough. Fold the dough four times during the first two hours. After shaping, let the dough rest in the fridge for twelve hours.

## Baking

Bake the loaf in a covered pot so the crust stays soft at first. Remove the lid after twenty minutes to brown the crust.
"""

RYE = """# Baking With Rye Flour

## Why rye is different

Rye flour holds much more water than wheat flour. Rye dough feels sticky and does not stretch like wheat dough. Rye bread needs a sour starter so that the crumb sets properly.

## Method

Mix rye flour with warm water and starter into a thick paste. Let the paste rise in its tin for about three hours. Rye loaves should cool for a full day before you cut them.
"""

DOCS = {"router": ROUTER, "soil": SOIL, "bread": BREAD, "rye": RYE}  # imported in this order
TAGS = {"rye": ["baking", "fermentation"], "soil": ["hydrology", "field-work"]}  # the tags "you already use"
HIGHLIGHTS = [  # (document, the sentence highlighted)
    ("router", "The router keeps the four highest-scoring blocks for each query."),
    ("router", "Memory use fell by 38% on inputs longer than 16,000 tokens."),
]

# Writing that stands for your own, as loose as notes to yourself are: what Tidy tidies and Plan chat plans around.
# The harness makes it when the first Tidy or Plan chat case runs, after every reading feature (see harness._yours).
TASKS = [  # open tasks; `in_days`: the day each is for, counted from today (None: any day)
    {"text": "buy rye flour and feed the starter", "minutes": 20, "in_days": 0},  # two things: a split
    {"text": "finish essay intro by friday!!", "minutes": 45, "in_days": None},  # a day the text implies, not set
    {"text": "dentist appointment", "minutes": 15, "in_days": 1},  # no verb
    {"text": "Read the Results section of the router paper", "minutes": 30, "in_days": None},  # already clear
]
NOTE = {"title": "Field trip plan", "body": (
    "bring the moisture sensors and spare batteries. meet at the hill gate at 8\n"
    "check the upper sensors first after rain , then the clay layer\n"
    "see [[Soil sensor log]] #field-work\n")}
ROUTINE = {"title": "Morning start", "steps": [{"text": "drink a glass of water", "minutes": 0}, {"text": "stretch for 10 minutes", "minutes": 0},
                                              {"text": "look over todays plan", "minutes": 5}]}

# One entry per run of a feature. `expect` (ask, library): "found" when the texts answer it, "not_found" when they
# do not, though they share its words (so the model is asked and has to say so). `min_docs` (library): the answer
# must cite verified quotes from at least this many documents. `kind` (tidy): what is tidied. `messages` (chat):
# the conversation, its last message yours; `minutes`: the minutes a day you set. Tidy and Plan chat come last.
CASES: list[dict] = [
    {"feature": "resume", "name": "router, after reading Method", "doc": "router", "read": "Method"},
    {"feature": "resume", "name": "soil, after reading Overview", "doc": "soil", "read": "Overview"},
    {"feature": "explain", "name": "router: which blocks are kept", "doc": "router", "sentence": "The router keeps the four highest-scoring blocks for each query.", "level": "student"},
    {"feature": "explain", "name": "soil: the deeper clay layer", "doc": "soil", "sentence": "Water reaches the deeper clay layer only after two or three days.", "level": "simple"},
    {"feature": "digest", "name": "router", "doc": "router"},
    {"feature": "digest", "name": "soil", "doc": "soil"},
    {"feature": "ask", "name": "blocks kept per query", "doc": "router", "question": "How many blocks does the router keep for each query?", "expect": "found"},
    {"feature": "ask", "name": "memory saved", "doc": "router", "question": "What was the memory use on inputs longer than 16,000 tokens?", "expect": "found"},
    {"feature": "ask", "name": "learning rate (not there)", "doc": "router", "question": "What learning rate was the router trained with?", "expect": "not_found"},
    {"feature": "ask", "name": "GPU used (not there)", "doc": "router", "question": "Which GPU was the block router benchmarked on?", "expect": "not_found"},
    {"feature": "library", "name": "cooling rye loaves", "question": "How long should rye loaves cool before you cut them?", "expect": "found"},
    {"feature": "library", "name": "starters, two texts", "question": "What does a sourdough starter hold, and why does rye bread need a starter?", "expect": "found",
     "min_docs": 2},
    {"feature": "library", "name": "oven heat (not there)", "question": "What oven temperature does rye bread need?", "expect": "not_found"},
    {"feature": "notes", "name": "router highlights, notes", "doc": "router", "source": "highlights", "kind": "notes"},
    {"feature": "notes", "name": "soil Measurements, flashcards", "doc": "soil", "source": "section", "section": "Measurements", "kind": "cards"},
    {"feature": "plan", "name": "three texts, a week", "docs": ["router", "soil", "bread"], "days": 7, "minutes": 15},
    {"feature": "plan", "name": "four texts, today only", "docs": ["router", "soil", "bread", "rye"], "days": 0, "minutes": 5},
    {"feature": "brainstorm", "name": "router highlights", "doc": "router"},
    {"feature": "organize", "name": "bread (fitting tags exist)", "doc": "bread"},
    {"feature": "tidy", "name": "your open tasks", "kind": "tasks"},
    {"feature": "tidy", "name": "a loose note", "kind": "note"},
    {"feature": "tidy", "name": "a morning routine", "kind": "routine"},
    {"feature": "chat", "name": "a week from a list (one you have)", "minutes": 60, "messages": [
        {"who": "you", "text": "Plan my week: read the Results section of the router paper, bake a rye loaf, and revise my soil notes (40 min)"}]},
    {"feature": "chat", "name": "a follow-up, tight days", "minutes": 30, "messages": [
        {"who": "you", "text": "I want to bake rye bread this week."},
        {"who": "model", "text": "Which steps should go on your plan, and how long does each take?"},
        {"who": "you", "text": "Mix the rye paste (20 min), shape the loaf (10 min), then bake the loaf (25 min)"}]},
    {"feature": "notechat", "name": "format the note", "messages": [{"who": "you", "text": "Make this note more formatted"}]},
    {"feature": "notechat", "name": "a story idea from it", "messages": [{"who": "you", "text": "Write an idea for a short story about this trip"}]},
]
