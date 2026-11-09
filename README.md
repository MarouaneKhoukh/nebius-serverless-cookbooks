<img src="photo-video-ai-search/media_search/static/brand/nebius-logo.svg" alt="Nebius" width="131" height="36">

# Nebius Serverless cookbooks

AI projects you can run on Nebius Serverless AI. Each cookbook includes sample data, deployment commands and instructions for inspecting the results.

The classification, evaluation, training, video and embedding recipes use **preemptible GPUs** to take advantage of lower rates when available. Each saves completed work so you can continue after an interruption.

Start with classification, then evaluate the model and fine-tune it:

1. [Classify Support Requests with Qwen](batch-inference-spot/README.md) — label a CSV of requests and save the answers.
2. [Evaluate a Model on Your Own Examples](evaluate-model-spot/README.md) — compare predictions with expected labels and review the mistakes.
3. [Fine-Tune Qwen and Resume Saved Training](fine-tune-resume-spot/README.md) — train on example requests, save a checkpoint and finish in a new Job.

The other cookbooks work with video, documents and photos:

- [Generate Video Clips from a List of Prompts](batch-video-generation-spot/README.md) — create and download three short clips with Wan.
- [Search Documents by Meaning](document-embeddings-spot/README.md) — turn documents into embeddings and find relevant passages with Qwen.
- [Search Your Photos and Create New Images](photo-video-ai-search/README.md) — search photos with Qwen3-VL and create missing images with FLUX.
