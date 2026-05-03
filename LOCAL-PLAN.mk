# Local validation notes
#
# Purpose:
#   Track local-only validation work that uses private customer campaign data.
#
# Guardrails:
#   - Do not copy proprietary campaign data, rendered PDFs, screenshots, or
#     customer-specific paths into this repository.
#   - Keep source changes generic and covered by neutral fixtures/tests.
#   - Use private data only to confirm behavior locally before applying generic
#     renderer, schema, or configuration changes.
#
# Current local validation:
#   - Featured-offers subtitles must remain legible after 4-up printing.
#   - Renderer defaults may be adjusted in source when the behavior is generic.
#   - Customer-specific tuning should live in private campaign data as component
#     style parameters once the generic hooks exist.

.PHONY: local-plan
local-plan:
	@printf '%s\n' 'See LOCAL-PLAN.mk for local/private validation guardrails.'
