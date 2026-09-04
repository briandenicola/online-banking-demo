# Session Log: Local Docker-Compose /api Gateway + Login Fix
**Date:** 2026-06-05 | **Context:** Local development setup refinement

## Overview
Session focused on fixing local docker-compose setup for React UI → API gateway routing. Python symlink setup, seed script URL output, and DNS search domain leak were addressed.

## Changes Applied

### 1. Python Symlink (MCR Azure Linux)
- **Root Cause:** Post-MCR migration: Python Dockerfile using relative path `python3` resolved correctly on host but needed explicit symlink in MCR Azure Linux images
- **Fix:** Added `RUN ln -sf python3.12 /usr/bin/python3` to all Python service Dockerfiles
- **Services:** ai-service, account-opening-service, budget-service, chatbot-service
- **Verification:** Containers start without "exec: python: not found" errors

### 2. Seed Script URL Output
- **Issue:** `task local:seed` completed without showing where to test the application
- **Fix:** Added final message to `scripts/seed-data.sh`: `🌐 View the app at: http://localhost:3000`
- **Impact:** Developers now have clear next steps after seeding completes

### 3. Local /api Gateway + DNS Search Domain Leak
- **Root Cause:** Docker host DNS search domain `denicolafamily.com` with ndots:0 leaked into compose containers; nginx resolver appended it to service names, routing `/api/*` calls to external wildcard hosts
- **Symptoms:** Login returned 405→502/404 errors
- **Solution:**
  - Created dedicated local-only nginx configs:
    - `infrastructure/local/gateway.nginx.conf` — routes `/api/*` to backend containers
    - `infrastructure/local/ui-app.nginx.conf` — proxies `/api/*` to gateway from UI container
  - Added `dns_search: ["."]` to gateway and ui-app services in docker-compose.yml
  - Reverted `src/ui-app/nginx.conf` to HEAD (AKS-safe, no local routes)
- **Verification:** Login HTTP 200, authenticated /api/accounts HTTP 200

## Key Design Decision
Two-setup architecture:
- **Local:** docker-compose with dedicated gateway service + local nginx overrides
- **Azure/AKS:** Istio owns ingress, clean UI image with no local logic
- This preserves production architecture while enabling local browser-compatible same-origin API calls

## Files
- `docker-compose.yml` — gateway service, dns_search, ui-app mount
- `infrastructure/local/gateway.nginx.conf` — NEW
- `infrastructure/local/ui-app.nginx.conf` — NEW
- `scripts/seed-data.sh` — seed script completion message
- Python Dockerfiles (ai-service, account-opening, budget, chatbot) — symlink
- `.squad/skills/docker-compose-dns-search-leak/` — DNS issue documentation

## Verification Status
✅ Login endpoint working
✅ API calls authenticated and routed correctly
✅ AKS deployment untouched
✅ Local development ready for testing
