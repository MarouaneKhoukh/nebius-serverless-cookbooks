<img src="photo-video-ai-search/media_search/static/brand/nebius-logo.svg" alt="Nebius" width="131" height="36">

# Nebius Serverless cookbooks

AI projects you can run on Nebius Serverless AI, plus a standalone Compute VM companion for preemptible document indexing. Each cookbook includes code, data setup, deployment instructions and ways to inspect the results.

The classification, evaluation, training, video and embedding recipes use **preemptible GPUs** to take advantage of lower rates when available. Each saves completed work so you can continue after an interruption.

Start with the batch-classification workflow. The evaluation and training recipes are separate examples:

1. [Classify a Support Backlog with Qwen](support-request-classification/README.md) — classify 3,080 banking queries in a GPU Job, save batches and review predictions alongside a CPU baseline.
2. [Evaluate a Model on a Real Test Set](model-evaluation/README.md) — score 3,080 BANKING77 predictions, compare a CPU baseline and inspect the mistakes.
3. [Fine-Tune Qwen on Real Banking Questions](fine-tuning-with-checkpoints/README.md) — train on 1,540 BANKING77 questions, resume a full checkpoint in a new Job and evaluate on 308 held-out questions.

The other cookbooks work with video, documents and photos:

- [Generate Video Clips from a List of Prompts](batch-video-generation/README.md) — run eight published VBench prompts through Wan and reuse completed MP4 downloads.
- [Build a Resumable Search Index on a Preemptible VM](document-search/README.md) — index 1,000 documents on a standalone VM, save progress in Object Storage and verify a controlled 600/400 resume.
- [Search Your Photos and Create New Images](photo-video-ai-search/README.md) — search photos with Qwen3-VL and create missing images with FLUX.
