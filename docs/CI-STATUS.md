# CI status baseline

The repository previously contained a multi-platform deployment workflow with a historical failure in the Render verification job. That failure must not be treated as proof of a current production outage. Current production health is determined by the active deployment platform and live health checks.

Until the workflow is migrated, changes to the legacy deployment workflow require its current blob SHA and should be made only after inspecting its present contents.
