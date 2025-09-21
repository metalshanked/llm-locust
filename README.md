# LLM Locust

## Running Locust WebUI and Backend Seperatly
WebUI
```bash
cd webui && yarn && yarn run dev
```
Backend
```bash
python api.py
```

## Build Locust WebUI and serve via backend
```bash
cd webui && yarn && yarn run build
cd .. && python api.py
```

## Offline Docker build and run (pre-download tokenizer and dataset)
The API uses a Hugging Face tokenizer (default: `NousResearch/Meta-Llama-3.1-8B-Instruct`).
To run fully offline inside the container, the Dockerfile pre-downloads both the tokenizer
and the Databricks Dolly 15k dataset (`databricks-dolly-15k.jsonl`) during the image build,
then enforces offline mode at runtime.

Build the image (online) once to cache assets:
```bash
# Optionally override which tokenizer to prefetch
# default: NousResearch/Meta-Llama-3.1-8B-Instruct
DOCKER_BUILDKIT=1 docker build \
  --build-arg TOKENIZER_ID=NousResearch/Meta-Llama-3.1-8B-Instruct \
  -t llm-locust:offline .
```

Then you can run the image completely offline:
```bash
docker run --rm -p 8089:8089 llm-locust:offline
```

Details:
- Hugging Face cache directory inside the image: `/hf-cache` (HF_HOME is set)
- Offline mode enforced via `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1`
- Dolly dataset cached at `/app/databricks-dolly-15k.jsonl`
- You can still pass a different tokenizer id or a local path at runtime via the
  `--tokenizer` CLI arg or via the Web UI form. For offline-only use, ensure those
  assets are present in `/hf-cache` or in a mounted local directory.

# How it works
![design diagram](image.png)


## TLS / Custom CA and self-signed certificates
If your target API uses a self-signed certificate, you can control SSL verification via the environment variable `LLM_LOCUST_SSL_CERT`.

Accepted values:
- Path to a CA bundle file (PEM) or a directory of hashed certs: the client will verify using that CA. Example: `LLM_LOCUST_SSL_CERT=/certs/my-ca.pem` or a directory `/certs/ca-dir`.
- Disabled keywords: `disabled`, `disable`, `false`, `0`, `no`, `insecure`, `skip`, `ignore` (case-insensitive). This disables SSL verification (insecure; use only for testing).
- Not set/empty: default system CA bundle verification is used.

Examples
- Docker with a custom CA file mounted:
  ```bash
  docker run --rm -p 8089:8089 \
    -e LLM_LOCUST_SSL_CERT=/certs/my-org-ca.pem \
    -v /host/path/to/certs:/certs:ro \
    llm-locust:offline
  ```
- Docker with verification disabled (insecure):
  ```bash
  docker run --rm -p 8089:8089 \
    -e LLM_LOCUST_SSL_CERT=disabled \
    llm-locust:offline
  ```
- Local run with a custom CA:
  ```bash
  set LLM_LOCUST_SSL_CERT=C:\\path\\to\\my-org-ca.pem
  python api.py
  ```
