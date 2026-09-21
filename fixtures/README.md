# Shared import fixtures

Two implementations now read the same backup files: the Python importers under
`api/app/adapters/`, and the Kotlin ones under `android/core/`. The schema
cannot drift, because it is generated from one source. Import *behaviour* has
no such protection — a fix for some FitNotes quirk on one side would not reach
the other, and the same backup would quietly produce different numbers
depending on which app read it.

These fixtures are that protection. Both test suites read them:

| file | what it is |
| --- | --- |
| `*.source.sql` | builds the file an app would hand us — a FitNotes backup, a Gadgetbridge export |
| `rows_*.sql` | the query that reads back what the import produced |
| `*.expected.csv` | exactly what that query must return |

Both suites build the source database, run their own importer into a fresh
canonical database, run the query, and compare against the `.csv` line for
line. A behavioural difference is then a failing build on whichever side
changed.

The comparison queries render every value to text **in SQL**. That is
deliberate: SQLite does the formatting, not Python or Kotlin, so `140.0` cannot
come out as `140` on one side and `140.0` on the other and fail for a reason
that has nothing to do with the data.

## Regenerating

Python is the reference implementation. When an importer's behaviour changes on
purpose, regenerate and read the diff:

```bash
cd api && uv run python ../scripts/refresh_fixtures.py
```

`api/tests/test_fixtures.py` fails when the checked-in files no longer match
what Python produces, and `android/core` fails when Kotlin disagrees with them.

## Timezone

Gadgetbridge stores epoch seconds, and which day a sample belongs to depends on
the timezone doing the bucketing — correct behaviour (you want the steps on the
day you walked them), but it means a fixture would otherwise give different
answers in different places. Both suites pin UTC for these tests.
