---
title: MCR Base Image Migration
skill_type: reference
updated: 2026-05-15
author: Turk
tags: [docker, mcr, azure-linux, base-images, rate-limits]
---

# MCR Base Image Migration

Guide for migrating Dockerfiles from Docker Hub base images to Microsoft Container Registry (MCR) to avoid Docker Hub anonymous pull rate limits.

## Why MCR?

**Problem:** Docker Hub has anonymous pull rate limits (100 pulls per 6 hours per IP). ACR build agents hit this limit frequently.

**Solution:** Microsoft Container Registry (MCR) has:
- **No rate limits** for Azure customers
- **No authentication required** from ACR build agents
- Microsoft-maintained, security-scanned images
- Better integration with Azure services

## Verified MCR Base Image Mappings

### Python

| Docker Hub | MCR Equivalent | Notes |
|-----------|----------------|-------|
| `python:3.11-slim` | `mcr.microsoft.com/azurelinux/base/python:3.12` | Python 3.11 not available on Azure Linux |
| `python:3.12-slim` | `mcr.microsoft.com/azurelinux/base/python:3.12` | Direct replacement |
| `python:3-slim` | `mcr.microsoft.com/azurelinux/base/python:3` | Tracks latest 3.x |

**Available tags:** `3`, `3.12`, `3.12.9-10-azl3.0.20260510` (pinned versions)

**Verify current tags:**
```bash
curl -s 'https://mcr.microsoft.com/v2/azurelinux/base/python/tags/list' | jq -r '.tags[]' | grep -E '^3\.'
```

### Node.js

| Docker Hub | MCR Equivalent | Notes |
|-----------|----------------|-------|
| `node:20-alpine` | `mcr.microsoft.com/azurelinux/base/nodejs:20` | Direct replacement |
| `node:20-slim` | `mcr.microsoft.com/azurelinux/base/nodejs:20` | Azure Linux is minimal (no separate "slim") |
| `node:24-alpine` | `mcr.microsoft.com/azurelinux/base/nodejs:24` | Node.js 24 LTS |

**Available tags:** `20`, `24`, `20.14`, `24.14`

**Verify current tags:**
```bash
curl -s 'https://mcr.microsoft.com/v2/azurelinux/base/nodejs/tags/list' | jq -r '.tags[]' | grep -E '^[0-9]+$'
```

### nginx

| Docker Hub | MCR Equivalent | Notes |
|-----------|----------------|-------|
| `nginx:alpine` | `mcr.microsoft.com/azurelinux/base/nginx:1.28` | Latest stable nginx |
| `nginx:1.28-alpine` | `mcr.microsoft.com/azurelinux/base/nginx:1.28` | Pinned major version |
| `nginx:1.25-alpine` | `mcr.microsoft.com/azurelinux/base/nginx:1.25` | Older stable |

**Available tags:** `1`, `1.28`, `1.25`

### Go (Golang)

| Docker Hub | MCR Equivalent | Notes |
|-----------|----------------|-------|
| `golang:1.26-alpine` | `mcr.microsoft.com/oss/go/microsoft/golang:1.26-azurelinux3.0` | Microsoft Build of Go with FIPS |
| `golang:1.25-alpine` | `mcr.microsoft.com/oss/go/microsoft/golang:1.25-azurelinux3.0` | Older version |

**Available tags:** `1.26-azurelinux3.0`, `1.26.3-azurelinux3.0` (pinned patches)

**Verify current tags:**
```bash
curl -s 'https://mcr.microsoft.com/v2/oss/go/microsoft/golang/tags/list' | jq -r '.tags[]' | grep azurelinux3.0 | grep -E '^1\.[0-9]+-azurelinux3.0$'
```

### Alpine (for runtime layers)

| Docker Hub | MCR Equivalent | Notes |
|-----------|----------------|-------|
| `alpine:latest` | `mcr.microsoft.com/azurelinux/base/core:3.0` | Full Azure Linux with shell |
| `alpine:latest` (for Go) | `mcr.microsoft.com/azurelinux/distroless/base:3.0` | **Preferred for Go** - no shell, minimal attack surface |

**Distroless advantages:**
- No shell, no package manager (security)
- Only includes runtime dependencies (glibc, ca-certificates, tzdata)
- Much smaller attack surface than full Alpine
- Perfect for static Go binaries (`CGO_ENABLED=0`)

## Azure Linux Migration Patterns

### 1. Python Service (Simple)

**Before:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY ./app ./app
COPY ./pyproject.toml ./
RUN pip install --no-cache-dir --root-user-action=ignore .

EXPOSE 8000

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**After:**
```dockerfile
FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app
COPY ./app ./app
COPY ./pyproject.toml ./
RUN pip install --no-cache-dir --root-user-action=ignore .

EXPOSE 8000

RUN useradd -r -s /sbin/nologin -M appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Key changes:**
- Base image: `python:3.11-slim` → `mcr.microsoft.com/azurelinux/base/python:3.12`
- User creation: `adduser` → `useradd` (Azure Linux uses `useradd`, not Debian's `adduser` wrapper)
  - `-r` = system user (UID < 1000)
  - `-M` = no home directory
  - `-s /sbin/nologin` = no login shell

### 2. Python Service with Debian Packages

**Before:**
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        dnsutils \
        iputils-ping \
        procps \
    && rm -rf /var/lib/apt/lists/*

# ... rest of Dockerfile
```

**After:**
```dockerfile
FROM mcr.microsoft.com/azurelinux/base/python:3.12

RUN tdnf install -y \
        curl \
        bind-utils \
        iputils \
        procps-ng \
    && tdnf clean all

# ... rest of Dockerfile
```

**Key changes:**
- Package manager: `apt-get` → `tdnf` (Azure Linux package manager)
- Package name mappings (see reference table below)
- Cleanup: `rm -rf /var/lib/apt/lists/*` → `tdnf clean all`

### 3. Node.js + nginx (Multi-stage)

**Before:**
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/build /usr/share/nginx/html
EXPOSE 8080
USER nginx
CMD ["nginx", "-g", "daemon off;"]
```

**After:**
```dockerfile
FROM mcr.microsoft.com/azurelinux/base/nodejs:20 AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
RUN npm run build

FROM mcr.microsoft.com/azurelinux/base/nginx:1.28
COPY --from=builder /app/build /usr/share/nginx/html
EXPOSE 8080
USER nginx
CMD ["nginx", "-g", "daemon off;"]
```

**Key changes:**
- Builder: `node:20-alpine` → `mcr.microsoft.com/azurelinux/base/nodejs:20`
- Runtime: `nginx:alpine` → `mcr.microsoft.com/azurelinux/base/nginx:1.28`
- No other changes needed (no custom packages)

### 4. Go Service with Distroless Runtime

**Before:**
```dockerfile
FROM golang:1.26-alpine AS builder
WORKDIR /app
RUN apk add --no-cache git
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /app
COPY --from=builder /app/server .
USER nobody
CMD ["./server"]
```

**After:**
```dockerfile
FROM mcr.microsoft.com/oss/go/microsoft/golang:1.26-azurelinux3.0 AS builder
WORKDIR /app
RUN tdnf install -y git && tdnf clean all
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server

FROM mcr.microsoft.com/azurelinux/distroless/base:3.0
WORKDIR /app
COPY --from=builder /app/server .
USER nobody
CMD ["./server"]
```

**Key changes:**
- Builder: `golang:1.26-alpine` → `mcr.microsoft.com/oss/go/microsoft/golang:1.26-azurelinux3.0`
- Builder package manager: `apk add` → `tdnf install`
- Runtime: `alpine:latest` → `mcr.microsoft.com/azurelinux/distroless/base:3.0`
- **Removed** `RUN apk --no-cache add ca-certificates` (distroless already includes ca-certificates)
- `USER nobody` (UID 65534) exists in distroless

**Why distroless for Go?**
- No shell, no package manager → smaller attack surface
- Only includes runtime dependencies (glibc, ca-certificates, tzdata)
- Perfect for static Go binaries (`CGO_ENABLED=0`)
- Significantly more secure than full Alpine

## Package Manager Reference

### Command Comparison

| Operation | Debian (`apt-get`) | Alpine (`apk`) | Azure Linux (`tdnf`) |
|-----------|-------------------|----------------|----------------------|
| Update cache | `apt-get update` | `apk update` | (not needed - no separate update) |
| Install | `apt-get install -y <pkg>` | `apk add --no-cache <pkg>` | `tdnf install -y <pkg>` |
| Cleanup | `rm -rf /var/lib/apt/lists/*` | (auto with `--no-cache`) | `tdnf clean all` |
| Search | `apt-cache search <pkg>` | `apk search <pkg>` | `tdnf search <pkg>` |

### Package Name Mappings

| Debian/Ubuntu | Alpine | Azure Linux | Notes |
|--------------|--------|-------------|-------|
| `dnsutils` | `bind-tools` | `bind-utils` | DNS tools (dig, nslookup) |
| `iputils-ping` | `iputils` | `iputils` | Ping utility |
| `procps` | `procps` | `procps-ng` | Process tools (ps, top) |
| `ca-certificates` | `ca-certificates` | (built-in or `ca-certificates`) | SSL certificates |
| `curl` | `curl` | `curl` | Same name |
| `git` | `git` | `git` | Same name |
| `build-essential` | `build-base` | `gcc` + `make` + `glibc-devel` | Compiler toolchain |
| `gnupg` | `gnupg` | (rarely needed with tdnf) | GPG tools |
| `lsb-release` | — | — | Not needed on Azure Linux |

**Finding package names:**
```bash
tdnf search <keyword>
```

## Common Gotchas

### Azure Linux Base Images: No shadow-utils

**Issue:** Azure Linux base images (e.g., `mcr.microsoft.com/azurelinux/base/python:3.12`) **do NOT ship with shadow-utils**. The `useradd` command is not available.

**Error:**
```
/bin/sh: line 1: useradd: command not found
```

**Solution:** Use numeric UIDs directly instead of creating named users:

```dockerfile
# ❌ Does NOT work on Azure Linux base images
RUN useradd -r -s /sbin/nologin -M appuser
USER appuser

# ✅ Works everywhere - recommended approach
USER 1001
```

**Why numeric UIDs are better:**
- No dependencies on shadow-utils or other user management packages
- Simpler, more portable (works on ALL base images)
- Kubernetes handles numeric UIDs without issues
- Recommended practice for minimal container images
- Smaller attack surface (fewer binaries in the image)

**When to use specific UIDs:**
- `USER 1000` — if Kubernetes manifest specifies `runAsUser: 1000`
- `USER 1001` — general-purpose non-root user (standard convention)
- `USER 65534` — "nobody" user (exists in most distros, including distroless)

**File ownership:** Most Python/Node.js apps only READ installed packages, so no ownership changes needed. If your app needs writable paths at runtime, use `COPY --chown=1001:1001` for those specific files/directories.

## User Creation Reference

### Command Comparison

| Distro | Command | Flags |
|--------|---------|-------|
| Debian/Ubuntu | `adduser --disabled-password --gecos "" --no-create-home <user>` | Wrapper around `useradd` |
| Alpine | `adduser -D -H <user>` | Busybox `adduser` |
| Azure Linux (full) | `useradd -r -s /sbin/nologin -M <user>` | Shadow-utils `useradd` (NOT in base images) |
| **Azure Linux base** | **`USER 1001`** | **Numeric UID (no shadow-utils)** |

### Azure Linux `useradd` Flags

- `-r` = system user (UID < 1000, non-login)
- `-M` = no home directory
- `-s /sbin/nologin` = no login shell
- `-u <uid>` = specific UID (e.g., `-u 1000`)

**With UID:**
```dockerfile
RUN useradd -r -s /sbin/nologin -M -u 1000 appuser
```

**System user (auto UID < 1000):**
```dockerfile
RUN useradd -r -s /sbin/nologin -M appuser
```

## Verification

### Check Available Tags

```bash
# Python
curl -s 'https://mcr.microsoft.com/v2/azurelinux/base/python/tags/list' | jq -r '.tags[]' | head -20

# Node.js
curl -s 'https://mcr.microsoft.com/v2/azurelinux/base/nodejs/tags/list' | jq -r '.tags[]' | head -20

# nginx
curl -s 'https://mcr.microsoft.com/v2/azurelinux/base/nginx/tags/list' | jq -r '.tags[]' | head -20

# Go
curl -s 'https://mcr.microsoft.com/v2/oss/go/microsoft/golang/tags/list' | jq -r '.tags[]' | grep azurelinux3.0 | head -20

# Distroless
curl -s 'https://mcr.microsoft.com/v2/azurelinux/distroless/base/tags/list' | jq -r '.tags[]' | head -10
```

### Test Local Build

```bash
cd path/to/service
docker build -t test-service .
```

### Test Multi-stage Build

```bash
docker build --target builder -t test-builder .  # Test builder stage only
docker build -t test-full .                      # Test full build
```

## Troubleshooting

### Issue: Package Not Found

**Error:**
```
Error: No package <package-name> available.
```

**Solution:**
```bash
# Search for package in Azure Linux repos
tdnf search <keyword>

# If not found, check if it's built-in or has a different name (see mapping table)
```

### Issue: User Creation Fails

**Error:**
```
useradd: invalid option -- '-'
```

**Solution:** You're using Debian `adduser` flags with `useradd`. Use Azure Linux flags:
```dockerfile
# Wrong (Debian)
RUN adduser --disabled-password --no-create-home appuser

# Right (Azure Linux)
RUN useradd -r -s /sbin/nologin -M appuser
```

### Issue: Distroless Container Won't Start

**Error:** Container exits immediately or shows "not found" error.

**Solution:** Distroless has no shell. Check:
1. Binary is static (`CGO_ENABLED=0` for Go)
2. Binary is in expected path (`COPY --from=builder /path/to/binary .`)
3. CMD uses array syntax: `CMD ["./binary"]` not `CMD ./binary`
4. `USER nobody` (UID 65534) exists in distroless - use it or numeric UID

### Issue: Python 3.12 Incompatibility

**Error:** Runtime error with Python 3.12.

**Solution:** 
- Check `pyproject.toml` for `requires-python` constraint
- Update dependencies: `pip install --upgrade <package>`
- If unfixable, use heavier devcontainers image: `mcr.microsoft.com/devcontainers/python:3.11`

## References

- [MCR Catalog](https://mcr.microsoft.com/)
- [Azure Linux Documentation](https://learn.microsoft.com/en-us/azure/azure-linux/)
- [Azure Linux Distroless](https://learn.microsoft.com/en-us/azure/azure-linux/distroless/overview)
- [Microsoft Go Images](https://github.com/microsoft/go-images)
- [Docker Hub Rate Limits](https://docs.docker.com/docker-hub/download-rate-limit/)
