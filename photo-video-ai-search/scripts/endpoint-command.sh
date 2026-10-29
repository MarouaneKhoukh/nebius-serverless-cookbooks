#!/usr/bin/env bash
# Print the reviewed deployment command. Never provision an Endpoint here.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: PROJECT_ID=project-... bash scripts/endpoint-command.sh [--dry-run]

Default: print a shell-quoted create command for a regular single-H100 Endpoint.
--dry-run: call the Nebius CLI with --dry-run; do not provision the Endpoint.

Required environment: PROJECT_ID (your real Nebius project ID).
Optional environment: ENDPOINT_NAME, SUBNET_ID, AI_AGENT.
The generated command enables token authentication. A real create operation
starts billable resources and must be a separate, deliberate action.
EOF
}

mode=print
if (($# > 1)); then
  usage >&2
  exit 2
fi
case "${1:-}" in
  '') ;;
  --dry-run) mode=dry-run ;;
  --help|-h) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

project_id=${PROJECT_ID:-}
project_id_lower=$(printf '%s' "$project_id" | tr '[:upper:]' '[:lower:]')
if [[ ! "$project_id" =~ ^project-[[:alnum:]]{6,}$ ]] ||
   [[ "$project_id_lower" =~ (example|placeholder|changeme|replace|yourproject|your-project) ]]; then
  printf '%s\n' 'Set PROJECT_ID to your real project-… ID; empty values and documentation placeholders are rejected.' >&2
  exit 2
fi

export AI_AGENT=${AI_AGENT:-codex}
endpoint_name=${ENDPOINT_NAME:-photo-video-embeddings}
if [[ -z "$endpoint_name" ]]; then
  printf '%s\n' 'ENDPOINT_NAME cannot be empty.' >&2
  exit 2
fi

server_args='-m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-VL-Embedding-8B --runner pooling --trust-remote-code --max-model-len 8192 --host 0.0.0.0 --port 8000'
command=(
  nebius ai endpoint create
  --parent-id "$project_id"
  --name "$endpoint_name"
  --image vllm/vllm-openai:v0.19.1
  --platform gpu-h100-sxm
  --preset 1gpu-16vcpu-200gb
  --container-port 8000/http
  --disk-size 500Gi
  --shm-size 16Gi
  --auth token
  --container-command python3
  --args "$server_args"
)
if [[ -n "${SUBNET_ID:-}" ]]; then
  if [[ ! "$SUBNET_ID" =~ ^vpcsubnet-[[:alnum:]]{6,}$ ]]; then
    printf '%s\n' 'SUBNET_ID must be a real vpcsubnet-… ID when supplied.' >&2
    exit 2
  fi
  command+=(--subnet-id "$SUBNET_ID")
fi

if [[ "$mode" == dry-run ]]; then
  command+=(--dry-run)
  if ! command -v nebius >/dev/null 2>&1; then
    printf '%s\n' 'Install and configure the Nebius CLI before choosing --dry-run.' >&2
    exit 127
  fi
fi

printf 'AI_AGENT=%q ' "$AI_AGENT"
printf '%q ' "${command[@]}"
printf '\n'

if [[ "$mode" == dry-run ]]; then
  "${command[@]}"
fi
