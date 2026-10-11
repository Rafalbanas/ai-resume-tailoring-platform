# VPS deployment

1. Create a deployment directory on the VPS and clone/copy the repository.
2. Copy `.env.example` to `.env` and use unique random secrets. The production defaults select `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, and `OLLAMA_MODEL=qwen3.5:9b`.
3. Copy `data/master_profile.example.json` to `data/master_profile.json`, then replace all fictional values with verified candidate facts.
4. Install/start Ollama on the host, pull `qwen3.5:9b`, and verify `curl http://127.0.0.1:11434/api/tags`.
5. Run `docker compose up -d --build` and verify both `/health` and `/health/provider` on `127.0.0.1:$CV_TAILOR_PORT` (port `8000` by default).
6. Configure the existing reverse proxy so your HTTPS hostname forwards to `http://127.0.0.1:8000` and preserves `Host`/forwarded headers. A sanitized example is provided in `deploy/nginx/cv.example.com.conf`.
7. Terminate TLS at the reverse proxy. Compose uses host networking so the container can reach host-loopback Ollama, while Uvicorn itself remains bound to loopback.
8. Back up the `data/` directory; it contains the master profile and generated applications.
9. Upload private reference CVs through the authenticated **Reference CVs** screen. Optionally upload a candidate photo through the **Profile** screen or place it under `data/profile_photo/`. Neither path is included in Git or the Docker image.

No production deployment is performed by CI.
