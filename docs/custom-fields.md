# Custom fields

A business adds its own fields to a kind of record: a vehicle plate on an asset, a hair type on a customer, a brand on a
product. An industry pack can ship fields too (`docs/industry-packs.md`). Fields are **data the business enters**; they are never used
for money or for stock (there is no money kind and no stock kind, on purpose).

## The model

| Table | What it holds |
|---|---|
| `kernel.custom_field_def` | One field: `entity_type`, `key` (fixed for life), `label`, `kind`, `choices`, `required`, `searchable`, `sort_order`, `active`, `source` (`business` or `pack:<name>`), `company_id` (null: the whole business) |
| `kernel.custom_field_value` | One row per record: `entity_type`, `entity_id`, `data` (jsonb: key to value), the record's `company_id` |

Both have `tenant_id` and forced row-level security. Kinds: `text` (500 characters), `number` (exact decimal text, 18 digits at most),
`date` (`YYYY-MM-DD`), `bool`, `choice` (one of the listed choices). A business may have 40 fields per record type; a record's values
are limited to about 15 KB. Numbers are stored as decimal text (`"2.5"`), never as floats.

## Which records can have fields

A unit offers a record type by implementing the extension point `kernel.custom_field_entity` (`CustomFieldEntity`, from `ziira.sdk`):

```python
@provides(CUSTOM_FIELD_ENTITY)
class AssetFields(CustomFieldEntity):
    entity_type = "jobs.asset"          # "<unit>.<record>"
    label = "Vehicle or item"           # shown on the settings page
    view_permission = "jobs.view"       # who may read the values
    edit_permission = "jobs.manage"     # who may change them
    def scope(self, session, entity_id):    # (company_id, branch_id), or None when there is no such record
        ...
```

Declare `kernel.custom_field_entity` under the unit's `[extends] implements`. Products offers `products.product` as the working example.
Only units that are on for the business take part. The API checks the **unit's own permission with the record's company and branch** (reading a
company-wide record needs the permission at any level in that company; changing it needs it for the company).

## For unit code (`ziira.sdk.custom_fields`)

* `definitions_for(session, entity_type, company_id)`: the active fields that apply (whole-business plus that company's), in order.
* `validate_values(definitions, values, existing=..., check_required=True)`: checks kinds, choices, lengths, required; returns the stored form.
  An empty value clears a field. Unknown or hidden keys are refused.
* `read_values(session, entity_type, entity_id)` and `write_values(session, entity_type, entity_id, values, company_id=...)`: `write_values`
  merges the keys given into the saved values under a row lock, so two people saving different fields at once both keep their change.
  It does **not** check permissions: call it from your own service after your own check.
* `find_entity_ids(session, entity_type, key, query)`: records whose searchable text field contains `query` (for a search box).
* `seed_definition(...)`: what packs use to add a field without overwriting one the business has.

## HTTP (`/api/v1/custom-fields`)

* `GET /entities` (manage): the record types offered.
* `GET ?entity_type=&company_id=&include_inactive=`: managers get all fields; anyone who may open the record type gets its active fields.
* `POST`, `PATCH /{id}`, `DELETE /{id}`, `PUT /order`: manage fields (permission `customfields.manage`, Owner by default). The key and kind never
  change. A pack's field can be hidden (`active: false`) but not deleted. Deleting a business field deletes its values.
* `GET|PUT /values/{entity_type}/{entity_id}`: the fields that apply to a record and their values; `PUT` changes only the keys sent.
  Every change is audited with the **keys only** (values may be personal data).

## Privacy

Values can hold personal data, so `kernel.custom_fields` is a `kernel.personal_data` provider: a data subject request finds text values that equal the
person's email, phone or id (a name matches loosely), exports them with the field labels, and erases text values (`[erased]`) and removes date values;
numbers, yes/no and choices stay (they identify nobody).

## Web

`CustomFields` (card with Edit, Save, Cancel and designed loading, error and empty states), `CustomFieldsForm` (the inputs, controlled) and
`useCustomFieldDefs` / `saveCustomValues` (for a create form that has no record id yet) come from `@/sdk`; `validateCustomValues` and `toPayload` are the
pure helpers. The business manages definitions in **Settings > Custom fields**.

## Not done

Custom fields are not shown in list columns or filters yet, and `searchable` has no database index (it is for small searches by a unit). Units must add
`<CustomFields>` to their own screens.
