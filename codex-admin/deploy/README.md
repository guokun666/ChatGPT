# Codex Admin/API deployment notes

This directory contains production deployment helpers for replacing the legacy
`/home/apple/codex-multi-proxy` service on the Google server.

Target server discovered from prior production work:

- SSH: `apple@35.240.158.3`
- SSH key: `~/.ssh/google_compute_engine`
- Legacy proxy dir: `/home/apple/codex-multi-proxy`
- Legacy proxy container: `codex-multi-proxy`
- New app dir: `/home/apple/codex-admin`
- Production port: `8091`
- Staging port: `8092`

Domains requested:

- Admin/backend UI: `codex-api-bk.4yailab.com` -> reverse proxy to `127.0.0.1:8091`
- Public API: `codex-api.4yailab.com` -> reverse proxy to `127.0.0.1:8091`

Both domains can point to the same container. The API key authorization protects
`/v1/*`; the admin UI/API should be additionally protected by the domain proxy or
future admin login if exposed publicly.

## Execution order

1. Staging deploy without touching old service:

```bash
ssh -i ~/.ssh/google_compute_engine apple@35.240.158.3
bash /home/apple/codex-admin/codex-admin/deploy/deploy_staging_on_gcp.sh
```

2. Smoke test staging on server:

```bash
KEY=$(cat /home/apple/codex-admin/codex-admin/data/model-family-codex-api-key.txt)
curl -sS -H "Authorization: Bearer $KEY" http://127.0.0.1:8092/v1/models | python3 -m json.tool
```

3. Switch production port from legacy proxy to new app:

```bash
bash /home/apple/codex-admin/codex-admin/deploy/switch_to_prod.sh
```

4. Configure reverse proxy/DNS:

```text
codex-api-bk.4yailab.com  -> http://127.0.0.1:8091
codex-api.4yailab.com     -> http://127.0.0.1:8091
```

5. Update model-family channel 86:

```bash
bash /home/apple/codex-admin/codex-admin/deploy/update_model_family_channel.sh
```

6. Verify full chain:

- `https://codex-api.4yailab.com/v1/models` with the generated key.
- `https://www.model-family.com/v1/chat/completions` using `admin001` token id 75.
- Production DB logs should show `model_name='gpt-5.4'` and `channel_id=86`.

## Safety notes

- The scripts do not print full access/refresh/id tokens.
- The generated model-family API key is stored only on the server at:
  `/home/apple/codex-admin/codex-admin/data/model-family-codex-api-key.txt`
- `switch_to_prod.sh` stops the old container but does not delete
  `/home/apple/codex-multi-proxy`, preserving rollback data.
