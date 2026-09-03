# Opsora audit next actions

1. Verify current production deployment and live health endpoints.
2. Inspect current CI workflow contents before modifying or removing legacy deployment steps.
3. Verify gateway authentication, provider routing, streaming, rate limits, CORS, and health/readiness behavior.
4. Verify Supabase RLS, security findings, performance findings, and application schema dependencies.
5. Verify frontend API/auth environment configuration and domain routing.
6. Only after dependency verification, remove obsolete deployment resources.

This checklist is intentionally conservative: production infrastructure is not deleted based on stale CI metadata.
