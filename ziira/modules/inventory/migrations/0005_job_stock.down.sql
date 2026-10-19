-- Fails while job movements exist (the ledger cannot be edited): remove the Jobs unit's data first.
alter table inventory.stock_movement drop constraint if exists stock_movement_movement_type_check;
alter table inventory.stock_movement add constraint stock_movement_movement_type_check
  check (movement_type in ('sale', 'sale_return', 'receipt', 'purchase_return', 'transfer_out', 'transfer_in',
                           'adjustment', 'count_variance', 'write_off', 'opening'));
