---
title: Docker Compose DNS Search Leak
author: Turk
updated: 2026-06-05
tags: [docker-compose, nginx, dns, local-dev]
---

# Docker Compose DNS Search Leak

## Symptom

A compose service can resolve another service with tools like `getent` or `wget`, but nginx proxying with `resolver 127.0.0.11` and variable `proxy_pass` returns unexpected 404/502 responses.

## Gotcha

Docker containers may inherit the host DNS search domain. With a host line such as `search denicolafamily.com` and Docker `options ndots:0`, nginx runtime resolution can try a short compose service name against the host search domain and hit an external wildcard host instead of the container.

## Fix Pattern

Add `dns_search: ["."]` to affected compose services, especially nginx gateway/proxy containers and callers that resolve compose service names.

```yaml
services:
  gateway:
    image: nginx:1.25-alpine
    dns_search: ["."]
```

Verify with:

```bash
docker exec <container> cat /etc/resolv.conf
```

The `search <host-domain>` line should be absent and Docker should show `Overrides: [search]`.

## AKS-Safe Local Proxy Pattern

If a UI nginx config is baked into the cloud image, do not edit it for local-only API proxying. Keep the clean image-baked config for AKS and mount a local-only override from docker-compose for `/api/*` proxying.
