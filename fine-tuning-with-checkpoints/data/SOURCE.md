# Sample data

`train.jsonl` contains 120 original synthetic support requests, created for this cookbook. There are 40 examples per label: `billing`, `technical`, and `account`. The fixture contains 60 scenarios, each with two introductory phrasings. Recreate it with `python3 scripts/make_training_data.py`.

`test.csv` contains the 30 separate synthetic held-out examples used in the evaluation cookbook. None of its request texts appears in the training file. Do not add it to the training configuration.

These files contain no customer data. The small synthetic test set illustrates a reproducible evaluation workflow; its scores are not evidence of real-world performance or guaranteed improvement. Review data rights and remove personal information before substituting your own data.

The original sample fixtures may be reused under CC0 1.0 Universal; see [LICENSE](LICENSE).
