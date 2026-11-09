# Recorded BANKING77 training results

Actual outputs from the 1,540-question training experiment: the base model scored 199/308 (64.6%) and the adapter scored 256/308 (83.1%) on the same selected test questions.

Open `report.html` or inspect the CSVs. `summary.json`, both session summaries, checkpoint events, trainer state and the checkpoint proof record the deliberate step-50 stop and completion at step 100 in a fresh Job. `dataset_provenance.json` contains the exact selection IDs and source hashes. The dataset attribution and unchanged license are in `DATA_SOURCE.md` and `DATA_LICENSE`.

This lightweight preview omits adapter weights, training JSONL and full optimizer checkpoints. Your own `result.zip` contains the adapter and prepared data; full recovery checkpoints remain in your bucket. See [validation](../../VALIDATION.md) for checks and limitations.
