# Build stage for WebUI
FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5-1730489338 AS webui-builder
SHELL ["/bin/bash", "-c"]

USER root

ENV PATH=/usr/node/bin:$PATH
# Set desired Helm and Kustomize versions
ENV HELM_VERSION="v3.16.2"
ENV KUSTOMIZE_VERSION="5.5.0"

RUN microdnf install -y git wget ca-certificates tar xz && \
  ARCH=$(uname -m) && \
  case $ARCH in \
  x86_64) NODE_ARCH="x64"; HELM_ARCH="amd64";; \
  aarch64) NODE_ARCH="arm64"; HELM_ARCH="arm64";; \
  armv7l) NODE_ARCH="arm"; HELM_ARCH="arm";; \
  esac && \
  echo "Detected Node.js architecture: $NODE_ARCH" && \
  echo "Detected Helm architecture: $HELM_ARCH" && \
  NODE_URL="https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-${NODE_ARCH}.tar.xz" && \
  curl -L $NODE_URL -o /tmp/node.tar.xz && \
  mkdir -p /usr/node && \
  tar -xf /tmp/node.tar.xz -C /usr/node --strip-components=1 && \
  npm update -g npm && \
  npm install -g yarn

WORKDIR /webui

# First copy only package dependency files
COPY webui/package.json webui/yarn.lock ./

# Install dependencies
RUN yarn

# Now copy the rest of the webui files
COPY webui/ .

# Build the webui
RUN yarn run build

# Final stage
FROM python:3.12.9-alpine3.21

# Set a fixed HF cache location inside the image
ENV HF_HOME=/hf-cache

WORKDIR /app

# Copy pyproject.toml for dependencies
COPY pyproject.toml .

# Install dependencies from pyproject.toml
RUN pip install --no-cache-dir .

# Pre-download tokenizer during build so runtime can be offline
# Allow override via build-arg TOKENIZER_ID (defaults to Meta-Llama-3.1-8B-Instruct)
ARG TOKENIZER_ID="NousResearch/Meta-Llama-3.1-8B-Instruct"
RUN python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('${TOKENIZER_ID}')" && \
    echo "Cached tokenizer for ${TOKENIZER_ID} into ${HF_HOME}"

# Pre-download Dolly dataset so runtime can be fully offline
RUN apk add --no-cache ca-certificates && \
    python -c "import urllib.request; urllib.request.urlretrieve('https://huggingface.co/datasets/databricks/databricks-dolly-15k/resolve/main/databricks-dolly-15k.jsonl','/app/databricks-dolly-15k.jsonl')" && \
    echo "Cached databricks-dolly-15k.jsonl into /app"

# Enforce offline mode at runtime (build step above has already cached assets)
# Disable Hugging Face tokenizers parallelism warning in forked processes
ENV TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false

# Copy WebUI build from first stage
COPY --from=webui-builder /webui/dist ./webui/dist

# Copy Python source files
COPY ./*.py .
COPY ./logging.conf .
COPY ./inputs.json .

# Expose FastAPI port
EXPOSE 8089

# Default command to run the API server
ENTRYPOINT ["python", "api.py"]
