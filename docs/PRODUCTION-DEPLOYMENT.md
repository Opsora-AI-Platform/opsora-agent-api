# Opsora Production Deployment Policy

## Source of truth
Production application deployments are owned by the configured platform-native deployment pipeline. GitHub Actions is a validation gate and must not deploy to legacy platforms unless an explicit migration is active.

## Legacy infrastructure
Render, Elastic, and ad-hoc Cloudflare deployment steps are considered legacy until explicitly verified as production dependencies. They must not cause the main branch CI to fail merely because an optional legacy service is unavailable.

## Required validation
- Python dependency installation, when `requirements.txt` exists.
- Python bytecode compilation for repository Python sources.
- JSON syntax validation.
- Platform deployment health checks are performed by the platform's own deployment system.

## Incident rule
A failed historical deployment run is not evidence of a current production outage. Current production status must be verified against the active deployment and live health endpoint before making corrective changes.
