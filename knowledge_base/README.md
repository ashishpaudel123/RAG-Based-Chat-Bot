# Knowledge base

Put one knowledge record per Markdown file in this folder (subfolders are fine), following
[`_TEMPLATE.md`](_TEMPLATE.md). The YAML block at the top becomes the document's source metadata
(source type, authority tier, section, status, effective dates, official URL, last-verified date,
verification status); the body is chunked and indexed.

```bash
cd backend
python -m app.cli ingest ../knowledge_base            # upload + index every record
```

* Records with `verification_status: pending` are stored but **never used to answer** until an admin
  marks them `verified` (Admin → Knowledge base → Edit). Check each record against the official
  source before verifying it.
* Uploading a file whose `id` matches an existing current record creates a **new version**; the old
  one becomes `superseded` and is kept for historical questions.
* Put district/office-specific practice (e.g. a DAO citizen charter) in separate records with
  `district:` set and `source_type: dao_charter` — never mix it into national-law records.
* Files named `README*` or starting with `_` are ignored by `ingest` and by the evaluation harness.

Evaluate with `python evaluation/run_eval.py --corpus knowledge_base --questions evaluation/questions_citizenship.json`
(add `--include-pending` to test records before they are verified).
