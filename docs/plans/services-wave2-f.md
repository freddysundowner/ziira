# Wave 2, agent F: claims unit

Done: unit `claims` (migration, domain, services, API, public.py, hooks, 9 Intelligence checks with plain en/sw text, pulse,
privacy, integrity check, files integration: `claims.claim` attachable, shareable photos on the response link), docs/claims.md,
pos.public additions (invoice_lines, invoice_states, credit_invoice_lines, receive_invoice_payment), `claim_estimate` message
template, web module `frontend/src/modules/claims` (list, claim page, payers, ageing, response page `/claim-response/:token`,
`ClaimPanel` in public.ts), tests (tests/test_claims.py 16 passing, domain tests, vitest).
Also done: tests/test_claims_intel.py, site catalog entries, schema.d.ts regenerated, privacy test list.
Cut / not done: the real-browser walk-through of a full insurer claim (not run), robustness valid_body hint, editions.toml entry (lead).
Doubts: no write-off in POS (accepted short pay stays open in POS); POS permissions needed for invoice/credit/receipt.
Resume: `set -a; . ./.env; set +a; .venv/bin/python -m pytest tests/test_claims.py tests/test_architecture.py tests/test_privacy.py -q`
