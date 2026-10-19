# Pack Garage

An **industry pack**: the data a kind of business starts with. It has no tables and no logic. When it is
switched on, each unit that has a `data/<unit>.toml` here copies it into the business's own tables
(adding only what is missing).

| File | Goes to |
|---|---|
| `data/pack.toml` | the pack's own settings: the units it feeds, the editions it is recommended for |
| `data/products.toml` | Products: service items with a usual duration |
| `data/custom_fields.toml` | Custom fields on records (read by the kernel) |

```bash
ziira plugin check .       # static checks
ziira plugin test .        # this pack's tests (they validate the data files)
ziira apply-packs          # seed switched-on packs again (safe to repeat)
```

See docs/industry-packs.md for every data file and what each unit's seeder accepts.
