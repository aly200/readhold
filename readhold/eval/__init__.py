"""The evaluation harness (AI plan, milestone 4.1): one command prints scores for every AI feature.

    uv run python -m readhold.eval              the model in your Settings
    uv run python -m readhold.eval --stand-in   a fake model, to check the harness itself

- `harness.py`  the command: a throwaway Readhold folder, the sample texts, each feature through its own route
- `samples.py`  the fixed sample set: four short texts written for it, tags, highlights, tasks, a note and a
                routine standing for your own (for Tidy and Plan chat), and the cases
- `score.py`    the scores, counted in code from the stored results and the AI log, and the table
- `standin.py`  the stand-in model, answered in-process through `Port.use_stand_in`
"""
from .harness import main, run

__all__ = ["main", "run"]
