# Catallaxy — SSL Gateway

> [Русская версия](README.ru.md)

A zero-config reverse proxy with automatic Let's Encrypt SSL. No NGINX or Certbot required.

## Features
- Gets and renews SSL certificates automatically.
- Proxies requests to `X-Agent-Endpoint` header or `?endpoint=` parameter.
- Adds standard CORS headers.
- `GET /img?url=<http-image-url>` — image proxy so https frontends can load
  images hosted on http agents without mixed-content blocks.
  - PNG / JPEG / GIF / WebP only (SVG blocked)
  - 5 MB response cap
  - cookies and `Authorization` are stripped both ways
  - private-network targets blocked by `safeDialContext`

## Run via Docker
Make sure your domain's A-record points to your server's IP.

```bash
docker build -t ssl-gateway .

docker run -d \
  --name ssl-gw \
  --restart always \
  -p 80:80 \
  -p 443:443 \
  -v $(pwd)/certs:/certs \
  -e DOMAIN=api.yourdomain.com \
  ssl-gateway
```

## Logs

```bash
docker logs -f ssl-gw
```
