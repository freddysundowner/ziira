# Licensing: outright purchase and self-hosted copies

A business can subscribe (SaaS, `docs/platform-admin.md`) or buy Ziira outright and run its own copy. A licence is a
JSON file whose body is signed with the vendor's Ed25519 private key over its canonical form (sorted keys, no spaces).
A copy holds only the **public** key (`ZIIRA_LICENCE_PUBLIC_KEY`, base64 of 32 bytes) and can check, never make, a licence.

## Vendor side

```bash
ziira licence keygen --out /secure/place          # licence-signing.key (0600) + the public key to give to copies
ziira licence issue --customer "Acme" --units products,inventory --max-users 10 --max-branches 3 \
    --valid-until 2031-01-01 --update-until 2028-01-01 --grace-days 30 [--instance ID] [--plan CODE] [--email ...] \
    [--key FILE | ZIIRA_LICENCE_SIGNING_KEY_FILE] --out acme.ziira-licence
ziira licence revocations --out revocations.ziira-licence      # signed list of revoked licence numbers
```

The same is in Super Admin > Licences on the vendor's SaaS deployment (needs `ZIIRA_LICENCE_SIGNING_KEY_FILE` there;
`platform.licences`). Records are in `master.licence` (no private key is stored). Omit `--valid-until` for a perpetual
licence; `--update-until` states until when updates are included (shown to the customer, not enforced by the code: the
customer simply stays on the version they have). `--instance` binds to one installation (`ziira licence instance-id` on
the customer's copy gives the id). Back the signing key up offline; if it is lost, no new licence can be made.

## Customer side

Set `ZIIRA_DEPLOYMENT_MODE=selfhosted` and `ZIIRA_LICENCE_PUBLIC_KEY`, then `ziira licence install FILE` (or paste/upload
on Settings > Plan & billing, which shows the licence in this mode: customer, number, units, limits vs use, expiry,
renewal reminder, instance id). `ziira licence status` (exit 1 when read-only), `verify FILE`, and
`ziira licence revocations FILE` to install a signed revocation list. `ZIIRA_LICENCE_REQUIRED=true` makes an instance
without a valid licence read-only (leave false in development).

## What is enforced

Units and limits (users, branches, companies) from the licence, the same refusals as plans (`not_in_plan`,
`plan_limit_reached`). Time: valid until `valid_until`; the **warning** starts 30 days before the end; after the end a
**grace period** (`grace_days`, default 30) keeps everything working with a warning; then the instance is **read-only**
(402 `subscription_ended`, reads and till uploads work). Revoked, wrong-instance and clock-rollback states are read-only
too. Nothing is ever deleted. A signed revocation list is the only way a copy learns of a revocation before expiry.

Clock: the latest time seen is stored; a clock earlier than that by more than `ZIIRA_LICENCE_CLOCK_TOLERANCE_HOURS`
(24) makes the licence read-only until the date is corrected.

## Threat model, honestly

Checks stop casual sharing and edits: a licence cannot be forged without the private key, an edited file is refused,
a bound licence works on one installation. They do **not** stop a determined administrator of a self-hosted machine, who
can patch the code, replace the public key, or manipulate the clock and the stored "last seen" time. The contract, the
support and update terms are the real control. Revocation without a revocation list takes effect only at expiry.
