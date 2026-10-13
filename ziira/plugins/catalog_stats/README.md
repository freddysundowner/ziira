# Catalog statistics (example plugin)

Shows how a plugin works. Remove it once real plugins exist.

- Own schema `plg_catalog_stats`, created and removed by its migrations.
- Subscribes to `product.created` and updates a counter in the same transaction.
- Adds `GET /api/v1/plugins/catalog-stats` (permission `catalog_stats.view`; Branch Manager and
  Accountant get it by default).
- Requires the `products` module.

```bash
ziira install catalog_stats                # offer it on the platform
ziira enable <tenant> catalog_stats        # creates plg_catalog_stats in that tenant's database
ziira disable <tenant> catalog_stats       # data kept
ziira remove <tenant> catalog_stats        # drops its tables from that tenant's database
ziira uninstall catalog_stats              # only when no tenant database has it
```
