# BANKING77 source and license

This cookbook uses **BANKING77**, published by PolyAI with *Efficient Intent Detection with Dual Sentence Encoders* (Casanueva et al., 2020). It contains English online-banking queries labeled with 77 fine-grained intents. It is a human-authored benchmark, not an export of production banking logs. The publisher's [dataset card](https://huggingface.co/datasets/PolyAI/banking77) identifies expert-generated language and annotations; the original paper does not specify a crowdsourcing procedure.

## Original release

- [Publisher repository](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data)
- Fixed revision: `57ec275d8078af65b7731c2a98be812d844a6d6b`
- [Paper](https://aclanthology.org/2020.nlp4convai-1.5/)
- Training: **10,003** examples; test: **3,080** examples, **40 per intent**. No additional validation split is supplied.
- Original CSV columns: `text,category`.

| File | SHA-256 |
| --- | --- |
| [train.csv](https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/train.csv) | `b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b` |
| [test.csv](https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/test.csv) | `d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d` |
| [categories.json](https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/categories.json) | `53261da888122daf2d120d925458631d9619e15d82e56052e7a42e535ce32b63` |
| [LICENSE](https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/57ec275d8078af65b7731c2a98be812d844a6d6b/LICENSE) | `7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661` |

The loader verifies bytes, checksums, counts and taxonomy before use. Downloads are cached locally under the selected cache directory, in a revision-specific folder. These are disposable input copies, not recovery storage for completed model results. The machine-readable pin is in [source.json](source.json).

## Preparation and separation

`prepare_data.py` creates `id,prompt,expected` CSV records from the **test split**. IDs such as `banking77-test-000001` refer to the original 1-based source record, before shuffling. It preserves text and exact category spelling, including `Refund_not_showing_up` and `reverted_card_payment?`.

The test file is grouped by intent upstream. The loader shuffles it with `random.Random(seed)` before applying a limit. By default, seed 42 and limit 0 select all 3,080 rows. Limit 32 is a smoke check, not a representative quality benchmark.

Training rows have separate `banking77-train-...` IDs. The CPU baseline fits all training rows. Qwen receives one original training example per intent (77 total) in its prompt, selected deterministically by proximity to 12 words among texts up to 160 characters, with source ID as the tie-breaker. These examples define the labeling convention; the cookbook does not fine-tune Qwen. Expected test labels are for scoring only and are never included in the prompts. New user CSVs may omit expected labels and do not need BANKING77-style IDs.

## Attribution and redistribution

BANKING77 is licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). The complete upstream license is preserved, unchanged, in [LICENSE](LICENSE). The code repository's license does not replace the dataset license.

When sharing this data or an adapted copy, retain supplied attribution and notices, link the source and license, identify modifications, and do not imply the publisher endorses this cookbook. The transformations made here are the added IDs, renamed CSV fields, deterministic row order and optional subset selection; the original text and labels are unchanged.

Attribution:

> BANKING77 by PolyAI. Iñigo Casanueva, Tadas Temčinas, Daniela Gerz, Matthew Henderson and Ivan Vulić. *Efficient Intent Detection with Dual Sentence Encoders*. Proceedings of the 2nd Workshop on Natural Language Processing for Conversational AI, ACL, 2020. Source: PolyAI-LDN/task-specific-datasets, revision 57ec275d8078af65b7731c2a98be812d844a6d6b. Licensed under CC BY 4.0. Adapted for this cookbook as described above.

```bibtex
@inproceedings{casanueva-etal-2020-efficient,
  title = "Efficient Intent Detection with Dual Sentence Encoders",
  author = "Casanueva, Iñigo and Temčinas, Tadas and Gerz, Daniela and Henderson, Matthew and Vulić, Ivan",
  booktitle = "Proceedings of the 2nd Workshop on Natural Language Processing for Conversational AI",
  year = "2020",
  publisher = "Association for Computational Linguistics",
  pages = "38--45",
  url = "https://aclanthology.org/2020.nlp4convai-1.5/",
  doi = "10.18653/v1/2020.nlp4convai-1.5"
}
```

## Split limitations

The official 3,080-row test split contains 3,079 unique texts after trimming whitespace and ignoring case. Six test rows have a normalized text also present in the training split. This cookbook keeps the official splits unchanged for reproducibility; these scores should not be treated as a new, fully unseen production evaluation.
