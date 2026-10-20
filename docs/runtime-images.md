# Runtime images

The Dockerfile uses Python 3.14 on an explicit Debian 13 (`slim-trixie`) base. It offers three runtime targets; no Alpine migration or Rust component is involved.

| Target | Responsibilities | Excluded Python packages |
| --- | --- | --- |
| `api` | FastAPI, authentication, candidate facts, Truth Lock, retrieval, LLM calls, storage and RPC clients | Playwright, WeasyPrint, python-docx, pypdf, PDFium, Pillow, HEIF |
| `documents` | Isolated PDF/DOCX generation, preview rasterization, reference extraction and photo normalization | Playwright and Chromium |
| `browser` | Isolated rendering of public job pages in Chromium | WeasyPrint, python-docx, pypdf, PDFium, Pillow, HEIF |
| `full` (default) | Backward-compatible all-in-one dependencies for existing CD/Kubernetes scripts and local full-stack development | None |

`requirements.txt` remains the sole source of exact direct dependency pins. `scripts/runtime_requirements.py` selects role subsets from it, so dependency updates do not need to modify several pin files. Small API dependencies are shared by all images; each worker adds only its own native stack. Dependency and browser installation precede source copying, allowing source-only rebuilds to reuse those expensive layers. Recursive Python/test caches, local tooling, private environment files and CV exports are excluded from the Docker context; image checks assert that only fictional example profiles are baked in.

The browser image installs regular Chromium with `--no-shell`: the application's seccomp launcher explicitly uses `chromium.executable_path`. It does not install a redundant headless-shell binary. The compatibility image retains both. The documents image explicitly preserves the legacy browser image's fonts, including Liberation Sans for Arial fallback and non-Latin/emoji coverage, rather than relying on Chromium to install fonts indirectly.

## Routing and isolation

Docker Compose selects the role targets explicitly:

- `cv-tailor`: API; only this service mounts candidate data.
- `processor-owner` / optional `processor-demo`: document workers on loopback ports 18002 / 18003.
- `browser-owner` / optional `browser-demo`: browser workers on loopback ports 18004 / 18005.

Document operations use `PROCESSING_URL` / `PROCESSING_TOKEN`. Browser rendering uses `BROWSER_PROCESSING_URL` / `BROWSER_PROCESSING_TOKEN`. Demo instances receive their independent `DEMO_PROCESSING_*` and `DEMO_BROWSER_PROCESSING_*` values through account-specific settings and request contexts. The demo context does not inherit the owner's browser endpoint when its own configuration is empty. Startup validates token lengths and independent owner/demo endpoints and credentials.

Generate independent tokens of at least 32 characters and set the two owner tokens in `.env`; set both demo tokens when enabling the demo profile. The workers receive only their own `PROCESSING_TOKEN`, no account mounts or AI credentials. Workers retain a read-only root filesystem, temporary storage, CPU/memory/PID bounds, dropped capabilities, no-new-privileges, and disposable sandboxed child processes. The HTTP processing server rejects operations belonging to the other role. Chromium's URL policy, request interception and kernel network restrictions remain in place.

The lean API requires remote processing and never falls back to a local parser when a worker is absent or unavailable. A missing browser service leads to the existing manual-offer fallback; it does not grant a local browser or access to another account's worker. Full/local development retains the legacy single processing endpoint when no dedicated browser endpoint is configured.

## Build and check without deployment

```sh
for role in api documents browser; do
  docker build --target "$role" --tag "cvtailor:split-$role" .
  docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --entrypoint python "cvtailor:split-$role" -m scripts.check_runtime_image "$role"
done
scripts/check_split_runtime.sh
```

The integration script creates temporary workers in a private internal Docker network, with synthetic credentials and no account volumes or public ports. It starts the API against them, checks the sandbox handshake, performs source-validated PDF/DOCX generation, extracts reference text, rasterizes a preview, checks private-URL rejection through browser RPC and cleans up its own containers/network. It does not invoke a model provider. Image checks assert role-specific package absence as well as required pin versions. CI runs these checks in addition to the existing compatibility-image job.

`docker build .` still produces the full compatibility image. Existing CD and Kubernetes deployment tools remain on that image until a separately reviewed role-image migration; this change does not run those tools or deploy to production. To use the split images locally, configure the tokens and use the updated Compose build targets. Building images alone does not change running containers.

## Measuring size

```sh
python -m scripts.measure_runtime_images \
  cvtailor:split-api cvtailor:split-documents cvtailor:split-browser --layers
python -m scripts.measure_runtime_images cvtailor:split-full --layers
```

The report distinguishes Docker's per-image uncompressed logical sizes from the combined uncompressed logical filesystem layers for a selected image set. The latter matches Docker history sizes to RootFS digests and counts each shared layer once. It validates layer counts, per-image totals and shared-layer sizes and refuses an estimated result if those checks fail. No image export or large temporary file is needed. Neither number is registry download size, physical disk consumption, RAM, or a latency benchmark. Do not add the three per-image sizes and call that shared disk usage. Owner/demo containers reuse the same role images. The retained `full` image and build cache consume additional disk if kept alongside the split images; nothing is pruned automatically.

The following local measurements were taken on Linux amd64 on 2026-10-19, using the same Python/Debian base and direct dependency pins for all four targets. Values are approximate and exclude build caches and retained older images.

Splitting adds one worker server process per account. The Compose document and browser workers each retain a 768 MiB memory limit; their combined limit is therefore higher than the former single worker limit. Smaller image sizes are not a claim of lower idle RAM or shorter model inference time. No automatic pruning of existing images, build caches, application history or generated CVs is performed.

## Local size results

| Image | Uncompressed logical size (decimal MB) |
| --- | ---: |
| `cvtailor:split-api` | 177.6 |
| `cvtailor:split-documents` | 415.0 |
| `cvtailor:split-browser` | 1096.7 |
| `cvtailor:split-full` | 1511.9 |

The three role images together use **1336.5 MB** of unique logical layers, compared with **1511.9 MB** for the compatibility image: about **11.6% less** by that metric. Shared layers are counted once using their RootFS digests. This is not a measurement of physical disk use, download size, idle RAM or runtime speed.

## Verification

- **95 targeted tests passed**: role dependency/import boundaries, document/browser RPC routing, owner/demo credential separation, fail-closed behavior, role operation rejection, Compose mounts/ports, existing resource limits, profile photos including HEIF, reference extraction and export quality.
- Real role images passed dependency absence/pin checks. The document image generated source-validated PDF/DOCX, extracted reference text and rasterized a preview. Chromium ran through the application's seccomp launcher; the browser image also blocked private-service requests from main pages, popups and blank-popup forms.
- The isolated API-to-worker integration passed startup sandbox handshake, health/login, PDF/DOCX, reference extraction, raster preview and browser-RPC private-URL rejection. The compatibility image passed the existing pinned-environment/import/sandbox checks.
- Compose configuration, Ruff, environment validation, README synchronization and whitespace checks passed. No production deployment, private-profile change or CV-history deletion was performed.

On this host the existing three browser-security pytest cases exceeded their 5-second navigation / 10-second overall budget while Chromium launched; the same timeout was reproduced with the unchanged renderer from HEAD. The container smoke uses a 30-second test navigation budget and passes the equivalent three request-blocking scenarios. Production timeouts and network restrictions were not changed. Initial cold-start checks during concurrent builds also timed out; subsequent isolated sandbox/RPC checks passed. A new full-suite green result or CI success is not claimed.
