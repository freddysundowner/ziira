# Products and Pricing

**Status:** working reference module. Use it as the template for every other module.

| | |
|---|---|
| Schema | `products` |
| Requires | kernel |
| Optional | inventory |
| Publishes | `product.created` |
| API | `/api/v1/products` |

## Endpoints

| Method | Path | Does |
|---|---|---|
| POST | `/uoms` | Create a unit of measure |
| POST | `/tax-codes` | Create a VAT / eTIMS tax code |
| POST | `/products` | Create a product |
| GET | `/products?search=` | List products |
| GET | `/products/{id}` | Get one product |

## How a request flows

```
api/routes.py            HTTP in, validates shape with api/schemas.py
  → services/create_product.py   the use case
      → domain/rules.py           business rules (pure, unit-tested)
      → repository/products_repo  database access (products schema only)
      → audit_record()            kernel audit trail (via ziira.sdk)
      → publish(product.created)  in-transaction subscribers + outbox
```

## For other modules

Import only `ziira.modules.products.public` (e.g. `find_product`). Never import
services, repository or models from another module.
