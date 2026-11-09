# BANKING77 training and evaluation data

BANKING77 is a human-authored banking-intent benchmark published by PolyAI with Casanueva et al., *Efficient Intent Detection with Dual Sentence Encoders* (NLP4ConvAI, 2020). It is not production banking logs.

- [Original dataset and authors](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data)
- [Paper](https://aclanthology.org/2020.nlp4convai-1.5/)
- Revision: `57ec275d8078af65b7731c2a98be812d844a6d6b`.
- Upstream splits: 10,003 training examples, 3,080 test examples, 77 intent labels.
- License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The unchanged upstream license is retained in `LICENSE` and every training result archive.

## Bounded default

`config/data.json` selects 20 original training rows per intent (1,540 total) and four original test rows per intent (308 total), using seed 42. Selection occurs before inference and never consults model scores. Original text, native label case/punctuation and source-record IDs are preserved. Training JSONL adds a system instruction and converts each source row into user/assistant messages; no synthetic utterances are generated.

Before sampling, training rows whose trimmed, case-folded text appears anywhere in the official test split are excluded. Duplicate normalized training and selected test texts are removed. `provenance.json` records excluded counts, exact IDs, source hashes and selected-file hashes. The original benchmark itself has six test rows sharing normalized text with training; these do not enter our training set. This is a reproducible experiment on a published benchmark, not a blind production evaluation.

The Job downloads the fixed upstream files and verifies their byte lengths, SHA-256 hashes, row counts and taxonomy before preparing local inputs. Checkpoints and results are written to Object Storage; model caches and downloaded source copies stay on the temporary VM. Large training JSONL is never injected through the CLI.

To change the selection, edit `config/data.json` before submitting a new run. `train_per_intent: 0` selects all eligible distinct training texts; adjust the training schedule accordingly. The default 100 optimizer steps with effective batch 16 process roughly 1,600 example presentations, about one pass over the 1,540-row selection, not the full 10,003-row source split.

Attribution: BANKING77 by PolyAI. Iñigo Casanueva, Tadas Temčinas, Daniela Gerz, Matthew Henderson and Ivan Vulić. *Efficient Intent Detection with Dual Sentence Encoders*. Proceedings of the 2nd Workshop on Natural Language Processing for Conversational AI, ACL, 2020. Licensed under CC BY 4.0. Adapted as described above; no endorsement by the authors is implied.
