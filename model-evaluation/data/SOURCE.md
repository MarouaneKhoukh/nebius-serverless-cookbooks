# Real BANKING77 evaluation inputs

The default input is a checksum-pinned export of 3,080 real BANKING77 test questions with their expected intents, actual Qwen predictions and a trained CPU baseline's predictions. The Qwen predictions were produced by preemptible Nebius Serverless AI Jobs in the batch-inference recipe. This evaluator scores those existing outputs locally; it does not rent another GPU to count correct labels.

## Source and attribution

- Dataset: BANKING77 by PolyAI, [original repository](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data).
- Dataset revision: `57ec275d8078af65b7731c2a98be812d844a6d6b`.
- Paper: Casanueva et al., [Efficient Intent Detection with Dual Sentence Encoders](https://aclanthology.org/2020.nlp4convai-1.5/), NLP4ConvAI 2020.
- License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), preserved unchanged in `LICENSE` and the input/result archive.
- Prediction export: commit `0926d4fc19e0842873f244f607c5affe888d17ab` of [this cookbook repository](https://github.com/MarouaneKhoukh/nebius-serverless-cookbooks). Exact public URL, size and SHA-256 are recorded in `reference.json`.

The default archive is bundled for a self-contained, account-free first run. `src/evaluate.py` verifies its pinned bytes, archive integrity, source input joins, row IDs, run contract and dataset license before scoring. The original text and native label spelling are preserved. Preparation only adds stable IDs and changes the input order; outputs are model observations, not manually supplied answers.

## What the comparison means

The Qwen run used Qwen3-4B-Instruct-2507 at revision `cdbee75f17c01a7cc42f958dc650907174af0554`, with one original training example per intent (77 total) in its prompt and no weight updates. The CPU word/bigram Naive Bayes baseline fitted the 10,003 original training rows. The two models therefore use different supervision budgets. These results do not establish which method is better with an equal annotation budget.

The official test split contains 3,079 unique normalized texts and six test rows whose trimmed, lowercased text also appears in training. The run keeps the official split; it is an exploratory benchmark comparison, not a fully unseen production evaluation. BANKING77 is human-authored benchmark language, not production bank logs.

## Fresh predictions

The optional finite GPU Job downloads the fixed original source files, verifies their bytes and hashes, and uses the same 3,080-row test split. Its full source pins are in `source.json` and `src/dataset.py`. Its 77 prompt examples are selected only from training rows. Input, model or prompt changes need a new run ID. You can evaluate another compatible complete `result.zip`, or compare CSV predictions from your own models on matching labeled questions.

Attribution: BANKING77 by PolyAI. Iñigo Casanueva, Tadas Temčinas, Daniela Gerz, Matthew Henderson and Ivan Vulić. *Efficient Intent Detection with Dual Sentence Encoders*. Proceedings of the 2nd Workshop on Natural Language Processing for Conversational AI, ACL, 2020. Licensed under CC BY 4.0. Adapted for this cookbook as described above. No endorsement by the authors is implied.
