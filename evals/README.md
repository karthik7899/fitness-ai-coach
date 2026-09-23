# Coach evals

Each file in `scenarios/` is one situation the coach should handle well. It
holds the data, a question, and what a good answer does:

```json
{
  "name": "load-spike",
  "about": "What the scenario is testing, in a sentence.",
  "question": "Am I ramping up my training load too fast?",
  "seed": { "workouts": [{"day": -5, "sets": [["Back Squat", 100, 5]]}] },
  "expect": {
    "calls": ["get_training_load"],
    "avoids": ["log_set"],
    "quotes": [2.685],
    "grounded": true
  },
  "script": [
    {"call": "get_training_load", "args": {"start_date": "{today-6}", "end_date": "{today}"}},
    {"text": "Your acute:chronic ratio is 2.685 today…"}
  ]
}
```

## Seed

Days are relative to the day the scenario runs (`"day": -5`), and so are dates
in the question and the script (`{today}`, `{today-6}`). The tools and the
coach's prompt both work from the real date. A scenario pinned to fixed dates
would drift out of every "last month" window within weeks.

| key | holds |
| --- | --- |
| `exercises` | `{name, category, muscles}`. If left out, you get the three the test suites use: Back Squat, Bench Press, Sled Push. |
| `workouts` | `{day, sets}`. Each set is `[exercise, weight_kg, reps]`, with an optional fourth element `true` for a warmup. |
| `daily_metrics` | `{day, metric, value, unit}`, with an optional `source`, which defaults to `gadgetbridge`. |
| `notes` | `{kind, content}`: standing facts the coach already knows. |

## Expectations

Every expectation becomes one pass/fail check. A run passes when all of its
checks pass.

| key | passes when |
| --- | --- |
| `calls` | Each entry was called. An entry can be a list of alternatives, and any one of them is enough. |
| `avoids` | None of these tools was called. |
| `quotes` | The answer states each figure. This uses the grounding check's matching rules, so `107.5 kg`, `107.50` and `0.1075 t` all count as quoting 107.5. |
| `grounded` | Every figure in the final answer was found in a tool result or in the athlete's own words. |
| `says` | For each entry, the answer contains at least one of the listed phrases. Matching ignores case. |
| `sets_added` | Exactly this many sets were logged. |
| `remembers` | A note was saved that contains this word. |

Keep `quotes` to figures that any good answer would include. Phrase lists in
`says` are for things like "there is no data", where the exact wording is
free. Give them generous alternatives.

## Script

The script is the model's side of the conversation, one response per step:

- `{"text": …}` is a final answer.
- `{"call": name, "args": {…}}` is one tool call.
- `{"calls": [{"name", "args"}, …]}` is several tool calls in one response.

CI plays the script instead of calling a model, so it judges nothing about
Gemini. What it proves:

- the scenario holds together, meaning its expected figures really come out of
  the tools on its seed data;
- the harness passes the scripted answer without sending it back;
- the Python and Kotlin coaches agree.

Both suites run every scenario: `api/tests/test_evals.py` and
`android/core/.../EvalTest.kt`.

When you add a scenario, write the script first, from what the tools actually
return on your seed data. If you guess a figure, the grounding check will say
so.

## Live runs

This grades the real model:

```bash
cd api && GEMINI_API_KEY=… uv run python ../scripts/run_evals.py
cd api && uv run python ../scripts/run_evals.py --only load-spike --repeat 5
cd api && uv run python ../scripts/run_evals.py --model gemini-3.8-pro
cd api && uv run python ../scripts/run_evals.py --scripted     # offline check of the runner
```

Each run gets a fresh SQLite database built from the shared schema. The runner
writes `results/report.md`, a summary table plus every failed run with its
checks and answer, and `results/results.json`, which has the full transcripts.
It exits with 2 if every run errored, which almost always means a bad key or a
bad model name. It exits with 1 if the pass rate falls below `--min-pass`.

To run it from GitHub instead:

1. Add a repository secret named `GEMINI_API_KEY`.
2. Open **Actions → Coach evals → Run workflow**.

The report appears on the run's summary page and is also attached as an
artifact.

Model output varies from run to run, so one failure is an anecdote. Use
`--repeat` before concluding that a prompt change helped or hurt.
