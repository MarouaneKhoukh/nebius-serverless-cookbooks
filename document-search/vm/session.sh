# Source from the document-search directory after connecting with SSH.
source .venv/bin/activate || return
source .env.vm || return
if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
    IFS= read -rs -p "S3 access key ID: " AWS_ACCESS_KEY_ID
    printf '\n'
fi
if [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    IFS= read -rs -p "S3 secret access key: " AWS_SECRET_ACCESS_KEY
    printf '\n'
fi
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
