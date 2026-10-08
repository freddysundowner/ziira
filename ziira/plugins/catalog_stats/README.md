# Catalog statistics (example plugin)

Shows how a plugin works. Remove it once real plugins exist.

- Own schema `plg_catalog_stats`, created and removed by its migrations.
- Subscribes to `product.created` and updates a counter in the same transaction.
- Adds `GET /api/v1/plugins/catalog-stats`.
- Requires the `products` module.

```bash
ziira install catalog_stats
ziira enable <tenant-id> catalog_stats
ziira disable <tenant-id> catalog_stats    # data kept
ziira uninstall catalog_stats              # only when no tenant has it enabled
```
