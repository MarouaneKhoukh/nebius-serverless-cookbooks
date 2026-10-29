[← Back to the cookbook](../README.md)

# Deploy the embedding model

An existing compatible, token-authenticated Endpoint is sufficient. Otherwise create a **custom Endpoint** in the [Nebius console](https://console.nebius.com), reviewing this configuration first:

| Setting | Value |
| --- | --- |
| Image | `vllm/vllm-openai:v0.19.1` |
| Entrypoint command | `python3 -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-VL-Embedding-8B --runner pooling --trust-remote-code --max-model-len 8192 --host 0.0.0.0 --port 8000` |
| Container port | `8000`, HTTP |
| Platform / preset | `gpu-h100-sxm` / `1gpu-16vcpu-200gb` |
| VM type | Regular |
| Disk / shared memory | 500 GiB / 16 GiB |
| Authentication | Token; save the generated token securely |

The pinned image and H100 configuration follow the existing [Nebius template](https://github.com/nebius/serverless-ai-cookbook/tree/main/templates/endpoint-qwen3-vl-embedding). The explicit 8192-token runtime context follows upstream's Qwen3-VL serving example and bounds this small recipe; it is not a statement of the model's maximum context. `--trust-remote-code` is retained from the template. Review the model and its Apache-2.0 license before deploying.

For a CLI route, the helper **prints** the complete, shell-quoted command and never provisions an Endpoint:

```bash
export PROJECT_ID=project-REPLACE_WITH_YOUR_REAL_ID
bash scripts/endpoint-command.sh
```

Replace the placeholder first; the helper rejects it. If your project has multiple subnets, set `SUBNET_ID` to the subnet you selected. The command includes `--parent-id`, token authentication, and agent identification, preserving a nonempty `AI_AGENT` value or using `codex`. It deliberately omits raw-public-IP and preemptible options.

After reviewing the command, you can request a **CLI dry run**:

```bash
bash scripts/endpoint-command.sh --dry-run
```

This invokes `nebius ai endpoint create ... --dry-run`; it does not create the Endpoint. Confirm the flags against your installed CLI and the [current Endpoint documentation](https://docs.nebius.com/serverless/endpoints/manage#how-to-create-an-endpoint). A real create is a separate action: review current pricing and quota, then deliberately run the printed command yourself or use the console. If sharing an agent transcript, keep the resulting token out of it.

Use the managed **HTTPS** URL from **Public endpoints**; a raw public IP is not required for this route. Model download/loading can take additional time after provisioning. The readiness check in the cookbook establishes a working text request; the subsequent ingestion must establish real image and video inference too.

## Stop or restart your Endpoint

Stop only the Endpoint you created for this recipe, using its actual ID:

```bash
export ENDPOINT_ID=aiendpoint-REPLACE_WITH_YOUR_ID
export AI_AGENT="${AI_AGENT:-codex}"
nebius ai endpoint stop --id "$ENDPOINT_ID"
```

Start it again when needed, then repeat the readiness check from the recipe directory:

```bash
nebius ai endpoint start --id "$ENDPOINT_ID"
python3 -m media_search check-endpoint --timeout 900
```

Stopping the Endpoint releases its running compute and boot disk while preserving configuration and its managed URL. Restarting reloads the model. The gallery's local media and Qdrant data stay on your computer. See [Serverless billing](https://docs.nebius.com/serverless/pricing-quotas).

For final removal, [delete the recipe's Endpoint](https://docs.nebius.com/serverless/endpoints/manage#how-to-delete-an-endpoint) from the console. Deletion invalidates its URL.
