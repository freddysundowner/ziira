# Plugging into other units (extension points and validation hooks)

Units normally talk through events. Two more sockets exist for cases where events are not enough.
Code is in `ziira/kernel/extensions.py`; Products and the `catalog_stats` plugin are the worked example.

| Socket | Use it when | Can block? |
|---|---|---|
| **Extension point**: a named contract (abstract class) | other units should *supply* something (SKU suggestions, a payment provider) | no |
| **Validation hook**: a named moment before an action | other units should be able to *refuse* the action | yes, by raising `ValidationFailed` |

Only units enabled for the tenant take part. Registration order does not matter.

## The owner offers a socket

1. Name it and put the contract in `public.py` (other units may import that file):
   ```python
   PRODUCT_BEFORE_CREATE = "products.product.before_create"
   SKU_SUGGESTER = "products.sku_suggester"
   class SkuSuggester(ABC):
       @abstractmethod
       def suggest(self, session, company_id, name) -> list[str]: ...
   ```
2. Declare it in `hooks.py` (`define_validation_hook(...)`, `define_extension_point(name, Contract)`).
3. List it in `manifest.toml`: `extension_points = [...]`, `validation_hooks = [...]`.
4. Use it in a service: `run_validators(session, PRODUCT_BEFORE_CREATE, draft)` before saving, or
   `implementations(session, SKU_SUGGESTER)` to collect the enabled implementations.

## Another unit plugs in

In its `hooks.py`: `@validate(PRODUCT_BEFORE_CREATE)` on a function `(session, draft)`, or
`@provides(SKU_SUGGESTER)` on a subclass of the contract. In its manifest:

```toml
[extends]
implements = ["products.sku_suggester"]
validates = ["products.product.before_create"]
```

## Rules

- A unit may plug only into sockets of itself, the kernel, or units it `requires` or lists as `optional`
  (checked at install).
- Code and manifest must agree (`tests/test_architecture.py`).
- Implementations are checked against the contract when registered, so mistakes fail at start-up.
- Validators run inside the transaction and block the operation. A validator that crashes also blocks,
  naming its unit (failing closed). Keep them fast (slow ones are logged). Slow or external work
  belongs in `@subscribe_after` handlers.

## Sockets the kernel offers

| Socket | Contract | Used for |
|---|---|---|
| `kernel.integrity_check` (extension point) | `IntegrityCheck.run(session, fix=False) -> list[str]` | A unit verifies its derived data against its source records. `ziira verify` runs every enabled unit's checks for every tenant (`--unit`, `--fix`; exit code 1 while problems remain); `ziira stock-verify` is Inventory's. Run it nightly. |
| `intel.check` (extension point, owned by Intelligence) | `IntelCheck.run(session, ctx) -> list[Candidate]` | A unit checks its own data every few hours and raises findings (a void spike, stock out, supplier price rise). See `docs/intelligence.md`. |
| `intel.baseline_metric` (extension point) | `BaselineMetric.samples(...)` | A unit supplies observations per day so Intelligence learns what is normal. |
| `command.pulse_source` (extension point, owned by the Command Center) | `PulseSource.figures(session, company_id, day) -> list[Figure]` | A unit adds its numbers to the dashboard and the daily brief. |
