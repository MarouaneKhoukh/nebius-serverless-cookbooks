<img src="photo-video-ai-search/media_search/static/brand/nebius-logo.svg" alt="Nebius" width="131" height="36">

# Nebius Serverless cookbooks

AI projects you can run on Nebius Serverless AI. Each cookbook includes code, data setup, deployment instructions and ways to inspect the results.

The classification, evaluation, training, video and embedding recipes use **preemptible GPUs** to take advantage of lower rates when available. Each saves completed work so you can continue after an interruption.

Start with document search or video generation:

1. [Build a Document Search Index with a Serverless Job](document-search/README.md) — index 1,000 documents with Qwen, save embeddings to Object Storage and search the collection by meaning.
2. [Generate a Video Dataset with Wan](batch-video-generation/README.md) — generate 200 clips from VBench prompts, review the dataset and resume unfinished batches.

More cookbooks:

- [Classify a Support Backlog with Qwen](support-request-classification/README.md) — classify 3,080 banking queries in a GPU Job, save batches and review predictions alongside a CPU baseline.
- [Evaluate a Model on a Real Test Set](model-evaluation/README.md) — score 3,080 BANKING77 predictions, compare a CPU baseline and inspect the mistakes.
- [Fine-Tune Qwen on Real Banking Questions](fine-tuning-with-checkpoints/README.md) — train on 1,540 BANKING77 questions, resume a full checkpoint in a new Job and evaluate on 308 held-out questions.
- [Search Your Photos and Create New Images](photo-video-ai-search/README.md) — search photos with Qwen3-VL and create missing images with FLUX.
