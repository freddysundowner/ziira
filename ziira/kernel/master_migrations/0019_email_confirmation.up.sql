-- A new owner goes straight into the system after choosing a password; confirming the email address happens afterwards,
-- from a link in the first email (the web app shows a banner until then). The link's token is stored as a hash only.
alter table master.registration
  add column confirm_token_hash text,
  add column confirm_sent_at timestamptz,
  add column email_confirmed_at timestamptz;
-- Everyone who registered before this change proved their email with the old link: they are already confirmed.
update master.registration set email_confirmed_at = verified_at where verified_at is not null;
create index registration_confirm_token_idx on master.registration (confirm_token_hash) where confirm_token_hash is not null;
comment on column master.registration.email_confirmed_at is 'When the owner used the link in the confirmation email (null = not yet; the web app asks them to).';
