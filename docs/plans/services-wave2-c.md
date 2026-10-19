# Services wave 2, agent C: time billing + professional pack

Status: backend, pack, web screens, docs and tests done and walked in a real browser. Not committed.

## Audit: gaps found in wave 1 (all closed unless marked open)
- Grouped invoice lines over 24 h could not be edited (minutes capped at 1440): closed (`BilledMinutes`, web uses `LONG_MINUTES`).
- `timebilling.project` / client not custom-field entities: closed (`timebilling.project`, `timebilling.client`).
- Review `problems` English only: closed (`problem_items` codes, web translates en/sw).
- Service-item picker filtered in the browser, first 100 only: closed (additive `product_type` query on `GET /products/products`, products unit not mine).
- No way to bill less than the work with a trace: closed (write-down with reason, write-off by partner; time never edited).
- Capped fee, partner review, narrative, receipts, recurring work, reminders, owner reports, pack: built (below).
- Open: fuzzer shop (`tests/test_robustness.py`) does not enable timebilling (lead decides); pulse/`public.unbilled_value` ignore a fee cap (slight overstatement); sample clients stay in Customers after removal; trust/client money is out of scope.

## Built
Migration `0002_professional`; services `engagements`, `nudges`, `notify`, `sample_data`, `setup`, `seed_industry`, `jobs.py` (hourly task `timebilling.run`); permission `time.partner`; 3 new checks (`work_overdue`, `review_waiting`, `realisation_low`) with plain en/sw text; 6 kernel message templates (en/sw); `intel.public.apply_check_defaults`; pack `pack_professional`; tests `tests/test_timebilling_professional.py`, `tests/test_pack_professional.py`.

## Resume
`set -a; . ./.env; set +a; .venv/bin/pytest tests/test_timebilling.py tests/test_timebilling_professional.py tests/test_pack_professional.py ziira/modules/timebilling/tests tests/test_architecture.py -q`; `ruff`, `mypy`, `lint-imports`; `cd frontend && npx tsc -b --noEmit && npx eslint src/modules/timebilling && npx vitest run src/modules/timebilling`; `make api-types` last.

## Browser walk (real browser, own tab, throwaway tenant, since dropped)
Owner and a second user (Branch Manager): sample practice loaded, example rate confirmed, week sent in by the owner, approved by the second user, invoice review with a write-down (reason required), narrative and standard wording, invoice issued; Overview, Deadlines, Settings tabs, project page (fee cap) checked; mobile 375 wide: no horizontal overflow on My week and Overview. Found and fixed: missed-time banner listed days before a person's first entry; issuing failed with "credit refused" for a client without a credit limit (sample clients now get one; review page explains it); two late sample tasks (started_days_ago).
Not exercised in the browser: receipt upload from a phone camera, retainer top-up dialog, Swahili view (key parity is tested).

## Doubts
- A new client has no credit limit, so the first invoice is refused until one is set in Customers (POS rule). A setting to skip it for service invoices belongs to POS.
- The first call to `/timebilling/setup` on a new tenant took several seconds once (settings row creation); not reproduced.
