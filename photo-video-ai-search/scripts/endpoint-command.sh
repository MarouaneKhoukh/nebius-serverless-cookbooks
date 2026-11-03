#!/usr/bin/env bash
# Print a reviewed command; real provisioning is always a separate action.
set -euo pipefail
case "${1:-}" in
  --help|-h)
    cat <<'HELP'
Usage: PROJECT_ID=project-... SUBNET_ID=vpcsubnet-... ENDPOINT_IMAGE=registry/image:tag \
  GPU_PLATFORM=gpu-h200-sxm GPU_PRESET=1gpu-16vcpu-200gb HF_TOKEN_SECRET=selector \
  PRICING_MODEL=regular \
  bash scripts/endpoint-command.sh [--dry-run]
Prints a token-authenticated, two-port Endpoint command; it does not create one.
Supported GPU pairs: gpu-h200-sxm / 1gpu-16vcpu-200gb, or
gpu-rtx6000 (also gpu-rtx6000-a) / 1gpu-24vcpu-218gb.
PRICING_MODEL is regular (default) or spot. Spot requires exactly one of:
  SPOT_PRICING_POLICY_ID=pricingpolicy-...  (recommended: a per-GPU-hour cap)
  SPOT_FOLLOWS_PRICE=yes                   (explicitly accept uncapped prices)
Use a current CLI with --on-demand, --preemptible and the Spot pricing flags;
0.12.299 was used to check these flags. Check your project's current quote,
Spot availability and the pricing policy's project/platform before creating.
The image must first be built from endpoint/Dockerfile and published by its owner.
HF_TOKEN_SECRET is a secret selector, never a Hugging Face token value.
--dry-run invokes only the CLI validation, never a real create operation.
HELP
    exit 0 ;;
  ''|--dry-run) ;;
  *) printf '%s\n' 'Use --help or --dry-run.' >&2; exit 2 ;;
esac
for name in PROJECT_ID SUBNET_ID ENDPOINT_IMAGE GPU_PLATFORM GPU_PRESET HF_TOKEN_SECRET; do
  value=${!name:-}
  if [[ -z "$value" || "$value" == *REPLACE* || "$value" == *YOUR_* ]]; then
    printf 'Set %s to its real non-secret identifier first.\n' "$name" >&2
    exit 2
  fi
done
[[ "$PROJECT_ID" =~ ^project-[[:alnum:]]{6,}$ && "$SUBNET_ID" =~ ^vpcsubnet-[[:alnum:]]{6,}$ ]] || {
  printf '%s\n' 'Use real project-… and vpcsubnet-… identifiers.' >&2; exit 2;
}
case "$GPU_PLATFORM/$GPU_PRESET" in
  gpu-h200-sxm/1gpu-16vcpu-200gb|gpu-rtx6000/1gpu-24vcpu-218gb|gpu-rtx6000-a/1gpu-24vcpu-218gb) ;;
  *) printf '%s\n' 'Choose a supported one-GPU H200 or RTX PRO 6000 platform/preset pair; see --help.' >&2; exit 2 ;;
esac
[[ ! "$HF_TOKEN_SECRET" =~ ^hf_[[:alnum:]]{20,}$ ]] || {
  printf '%s\n' 'HF_TOKEN_SECRET must be a stored secret selector, never a token value.' >&2; exit 2;
}
pricing_model=${PRICING_MODEL:-regular}
spot_policy=${SPOT_PRICING_POLICY_ID:-}
spot_follow=${SPOT_FOLLOWS_PRICE:-no}
[[ "$spot_follow" == yes || "$spot_follow" == no ]] || {
  printf '%s\n' 'SPOT_FOLLOWS_PRICE must be yes or no.' >&2; exit 2;
}
pricing_args=()
case "$pricing_model" in
  regular)
    [[ -z "$spot_policy" && "$spot_follow" == no ]] || {
      printf '%s\n' 'Clear Spot pricing settings when PRICING_MODEL=regular.' >&2; exit 2;
    }
    pricing_args=(--on-demand)
    ;;
  spot)
    if [[ -n "$spot_policy" ]]; then
      [[ "$spot_policy" =~ ^pricingpolicy-[[:alnum:]]{6,}$ && "$spot_policy" != *REPLACE* && "$spot_follow" == no ]] || {
        printf '%s\n' 'Use one real pricingpolicy-… ID, without SPOT_FOLLOWS_PRICE=yes.' >&2; exit 2;
      }
      pricing_args=(--preemptible --spot-pricing-policy-id "$spot_policy")
    elif [[ "$spot_follow" == yes ]]; then
      pricing_args=(--preemptible --follows-spot-price)
    else
      printf '%s\n' 'Spot requires SPOT_PRICING_POLICY_ID (recommended) or explicit SPOT_FOLLOWS_PRICE=yes.' >&2
      exit 2
    fi
    ;;
  *) printf '%s\n' 'PRICING_MODEL must be regular or spot.' >&2; exit 2 ;;
esac
export AI_AGENT=${AI_AGENT:-codex}
default_name=media-search-generate
if [[ "$pricing_model" == spot ]]; then default_name+=-spot; fi
command=(nebius ai endpoint create --parent-id "$PROJECT_ID" --name "${ENDPOINT_NAME:-$default_name}"
  --image "$ENDPOINT_IMAGE" --platform "$GPU_PLATFORM" --preset "$GPU_PRESET"
  --subnet-id "$SUBNET_ID" --container-port 8000/http --container-port 8001/http
  --disk-size 500Gi --shm-size 16Gi --auth token --env-secret "HF_TOKEN=$HF_TOKEN_SECRET"
  "${pricing_args[@]}" --async)
if [[ -n "${REGISTRY_SECRET:-}" ]]; then command+=(--registry-secret "$REGISTRY_SECRET"); fi
if [[ "${1:-}" == --dry-run ]]; then command+=(--dry-run); fi
printf 'AI_AGENT=%q ' "$AI_AGENT"
printf '%q ' "${command[@]}"
printf '\n'
if [[ "${1:-}" == --dry-run ]]; then "${command[@]}"; fi
