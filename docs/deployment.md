# VPS deployment

1. Create a deployment directory on the VPS and clone/copy the repository.
2. Copy `.env.example` to `.env`, use unique random secrets, and set `AI_PROVIDER=n8n`.
3. Copy `data/master_profile.example.json` to `data/master_profile.json`, then replace all fictional values with verified candidate facts.
4. Run `docker compose up -d --build` and verify `curl http://127.0.0.1:8000/health`.
5. Configure the existing reverse proxy so your HTTPS hostname forwards to `http://127.0.0.1:8000` and preserves `Host`/forwarded headers. A sanitized example is provided in `deploy/nginx/cv.example.com.conf`.
6. Terminate TLS at the reverse proxy. Keep port 8000 bound to loopback, as in `docker-compose.yml`.
7. Back up the `data/` directory; it contains the master profile and generated applications.

No production deployment is performed by CI.
