-- Stock issued to a job (repair, installation) and parts taken back off it are two new kinds of movement.
alter table inventory.stock_movement drop constraint if exists stock_movement_movement_type_check;
alter table inventory.stock_movement add constraint stock_movement_movement_type_check
  check (movement_type in ('sale', 'sale_return', 'receipt', 'purchase_return', 'transfer_out', 'transfer_in',
                           'adjustment', 'count_variance', 'write_off', 'opening', 'job_issue', 'job_return'));
