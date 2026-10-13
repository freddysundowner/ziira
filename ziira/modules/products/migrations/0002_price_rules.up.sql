-- One default price list per company (a branch's own list may also be marked default for that branch),
-- and one price per product, list and start date.
create unique index price_list_one_default on products.price_list (company_id, coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where is_default;
create unique index price_list_item_one_start on products.price_list_item (price_list_id, product_id, valid_from);
