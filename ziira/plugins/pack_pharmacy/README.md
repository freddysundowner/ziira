# Pack Pharmacy

An **industry pack**: the data a pharmacy, chemist or drug shop starts with. It has no tables and no logic. Ziira is not a
pharmacy management or medical record system; a pharmacy follows its own regulator's rules. See `docs/pack_pharmacy.md`.

| File | Goes to |
|---|---|
| `data/pack.toml` | the units it feeds and the editions it is recommended for |
| `data/products.toml` | Products: categories, units, example medicines (batch tracked, with reorder levels) |
| `data/custom_fields.toml` | Product fields (generic name, strength, form, prescription, controlled, storage) and one customer field |
| `data/purchasing.toml` | Purchasing: supplier templates |
| `data/intel.toml` | Intelligence: limits that suit a pharmacy (expiry warnings, price rises, reference notes) |
| `data/checklist.toml` | the first steps shown on Home |

```bash
ziira plugin check ziira/plugins/pack_pharmacy
ziira apply-packs          # seed again (safe to repeat)
```
