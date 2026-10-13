# Products and Pricing

**Status:** working reference module. Use it as the template for every other module.

| | |
|---|---|
| Schema | `products` |
| Requires | kernel |
| Optional | inventory |
| Publishes | `product.created` |
| API | `/api/v1/products` |
| Permissions | `products.view`, `products.manage`, `prices.manage` |
| Default roles | Branch Manager: view + manage · Finance Manager: view + prices · Cashier, Storekeeper, Sales Rep, Accountant: view · Owner: all |

## Endpoints

| Method | Path | Does | Needs |
|---|---|---|---|
| POST | `/uoms` | Create a unit of measure | `products.manage`, whole tenant |
| POST | `/tax-codes` | Create a VAT / eTIMS tax code | `products.manage`, whole tenant |
| POST | `/products` | Create a product | `products.manage` for that company |
| GET | `/products?search=` | List products (only companies the user may see) | `products.view` |
| GET | `/products/{id}` | Get one product (404 if out of scope) | `products.view` |

## How a request flows

```
api/routes.py            HTTP in, validates shape with api/schemas.py,
                         require_permission(...) rejects users without the permission
  → services/create_product.py   the use case
      → current_context().require(..., company_id=...)   scope check
      → check_company()           the company belongs to this tenant
      → domain/rules.py           business rules (pure, unit-tested)
      → repository/products_repo  database access (products schema, in the tenant's own database)
      → audit_record()            kernel audit trail (via ziira.sdk)
      → publish(product.created)  in-transaction subscribers + outbox
```

## For other modules

Import only `ziira.modules.products.public` (e.g. `find_product`). Never import
services, repository or models from another module.
