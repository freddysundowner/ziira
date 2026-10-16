-- AI providers managed in the Super Admin: one row per provider plugin (key encrypted, models chosen per feature,
-- price overrides, the data-use acknowledgement), the estimated spend per day, and an optional per-business provider.
-- Which providers exist is decided by plugins; nothing here names one. The platform-wide default provider and the
-- monthly spend cap are rows of master.platform_setting ('ai.default_provider', 'ai.monthly_cap_usd').

create table master.ai_provider (
  provider text primary key check (provider ~ '^[a-z0-9_]{2,40}$'),
  enabled boolean not null default false,
  secret_encrypted text,
  key_last4 text,
  base_url text,
  models jsonb not null default '{}',
  price_overrides jsonb not null default '{}',
  live_models jsonb,
  live_models_at timestamptz,
  last_tested_at timestamptz,
  last_test_ok boolean,
  last_test_message text,
  terms_ack_by text,
  terms_ack_at timestamptz,
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.ai_provider is 'The platform owner''s settings for each AI provider plugin. secret_encrypted is a Fernet token of the API key: write-only, never returned, logged or audited; key_last4 is all that is shown. models maps a feature (explain, rank, ask) to a model id; price_overrides maps a model id to {input, output} USD per million tokens. terms_ack_* records who accepted the provider''s data-use terms.';

create table master.ai_usage (
  day date not null,
  provider text not null,
  model text not null,
  tenant_id uuid not null,
  calls int not null default 0,
  tokens_in bigint not null default 0,
  tokens_out bigint not null default 0,
  cost_usd numeric(14, 6) not null default 0,
  primary key (day, provider, model, tenant_id)
);
create index ai_usage_tenant_ix on master.ai_usage (tenant_id, day);
comment on table master.ai_usage is 'Estimated AI spend per day, provider, model and business, from token counts and the price table. Counts and money only: no prompts, no names, no personal data.';

create table master.ai_tenant_provider (
  tenant_id uuid primary key references master.tenant(id) on delete cascade,
  provider text not null,
  reason text not null,
  set_by text not null,
  set_at timestamptz not null default now()
);
comment on table master.ai_tenant_provider is 'An operator-made exception: this business uses another AI provider than the platform default. Off unless a row exists.';
