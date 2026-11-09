<img src="photo-video-ai-search/media_search/static/brand/nebius-logo.svg" alt="Nebius" width="131" height="36">

# Nebius Serverless cookbooks

AI projects you can run on Nebius Serverless AI. Each cookbook includes sample data, deployment commands and instructions for inspecting the results.

The classification, evaluation, training, video and embedding recipes use **preemptible GPUs** to take advantage of lower rates when available. Each saves completed work so you can continue after an interruption.

Start with the batch-classification workflow. The evaluation and training recipes are separate examples:

1. [Classify a Support Backlog with Qwen](support-request-classification/README.md) — classify 3,080 banking queries in a GPU Job, save batches and review predictions alongside a CPU baseline.
2. [Evaluate a Model on Your Own Examples](model-evaluation/README.md) — compare predictions with expected labels and review the mistakes.
3. [Fine-Tune Qwen and Resume Saved Training](fine-tuning-with-checkpoints/README.md) — train on example requests, save a checkpoint and finish in a new Job.

The other cookbooks work with video, documents and photos:

- [Generate Video Clips from a List of Prompts](batch-video-generation/README.md) — create and download three short clips with Wan.
- [Search Documents by Meaning](document-search/README.md) — turn documents into embeddings and find relevant passages with Qwen.
- [Search Your Photos and Create New Images](photo-video-ai-search/README.md) — search photos with Qwen3-VL and create missing images with FLUX.
