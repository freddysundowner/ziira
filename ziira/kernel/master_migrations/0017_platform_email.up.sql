-- Platform email managed in the Super Admin: the credentials of each mail provider (encrypted, write-only), and a short
-- log of what the platform sent. Which provider is active, the sender, and the last test result are rows of
-- master.platform_setting ('email.provider', 'email.sender', 'email.last_test', 'email.last_success_at').

create table master.platform_email_provider (
  provider text primary key check (provider ~ '^[a-z0-9_]{2,40}$'),
  config jsonb not null default '{}',
  secrets_encrypted text,
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.platform_email_provider is 'The platform owner''s mail settings per provider. config holds the plain fields (host, port, security, username); secrets_encrypted is a Fernet token of a JSON object (password or API key): write-only, never returned, logged or audited.';

create table master.platform_mail_log (
  id bigserial primary key,
  sent_at timestamptz not null default now(),
  kind text not null,
  recipient_masked text not null,
  status text not null check (status in ('sent', 'failed')),
  provider text,
  detail text
);
create index platform_mail_log_sent_ix on master.platform_mail_log (sent_at desc);
comment on table master.platform_mail_log is 'What the platform emailed (registration, password reset, billing, test): when, what kind, the recipient masked (j***@gmail.com), whether the provider took it and why not. Never the message, never the full address, never a secret. Purged after the retention period.';
