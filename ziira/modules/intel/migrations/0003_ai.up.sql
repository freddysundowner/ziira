-- The AI layer: consent records, monthly usage, a log of every call to the AI provider, Ask Ziira conversations, the
-- stored ranking of findings, and the AI-written explanation of a finding. The log holds hashes and labels, never the
-- text sent, and never a key.

alter table intel.finding add column explanation_ai text;
alter table intel.finding add column explanation_ai_at timestamptz;
alter table intel.finding add column explanation_ai_tried_at timestamptz;
comment on column intel.finding.explanation_ai is 'Plain-language explanation written by the AI layer from the finding''s own figures (labelled AI-written wherever shown); explanation holds what a person said';

create table intel.ai_consent (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  user_id uuid references kernel.app_user(id),
  action text not null check (action in ('granted', 'revoked')),
  text_version text not null,
  language text not null default 'en',
  consent_text text not null,
  text_hash text not null,
  provider text not null,
  model text
);
comment on table intel.ai_consent is 'Who agreed to AI processing for a company, when, and the exact text agreed; the latest row decides. Never changed.';
create index ai_consent_ix1 on intel.ai_consent (tenant_id, company_id, created_at);
alter table intel.ai_consent enable row level security;
alter table intel.ai_consent force row level security;
create policy tenant_isolation on intel.ai_consent
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create trigger ai_consent_immutable before update or delete on intel.ai_consent
  for each row execute function kernel.forbid_change();

create table intel.ai_usage (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  company_id uuid not null references kernel.company(id),
  month date not null,
  input_tokens bigint not null default 0,
  output_tokens bigint not null default 0,
  calls integer not null default 0,
  updated_at timestamptz not null default now(),
  unique (tenant_id, company_id, month)
);
comment on table intel.ai_usage is 'Tokens the AI layer used per company and calendar month (the budget is checked against it).';
alter table intel.ai_usage enable row level security;
alter table intel.ai_usage force row level security;
create policy tenant_isolation on intel.ai_usage
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.ai_call_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid references kernel.company(id),
  user_id uuid references kernel.app_user(id),
  purpose text not null,
  ref_type text,
  ref_id uuid,
  provider text,
  model text,
  prompt_hash text,
  tool_calls jsonb not null default '[]',
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  latency_ms integer,
  status text not null,
  detail text
);
comment on table intel.ai_call_log is 'Every call to the AI provider (or refusal to make one): who asked, why, a hash of what was sent, the tools the model called, tokens, time and outcome. No prompt text, no keys.';
create index ai_call_log_ix1 on intel.ai_call_log (tenant_id, company_id, created_at desc);
alter table intel.ai_call_log enable row level security;
alter table intel.ai_call_log force row level security;
create policy tenant_isolation on intel.ai_call_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.ask_session (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  user_id uuid not null references kernel.app_user(id),
  title text not null,
  last_at timestamptz not null default now()
);
comment on table intel.ask_session is 'A person''s conversation with Ask Ziira. Visible to that person, and to holders of ai.manage for audit.';
create index ask_session_ix1 on intel.ask_session (tenant_id, user_id, last_at desc);
alter table intel.ask_session enable row level security;
alter table intel.ask_session force row level security;
create policy tenant_isolation on intel.ask_session
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.ask_message (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  session_id uuid not null references intel.ask_session(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  sources jsonb not null default '[]',
  tools_used jsonb not null default '[]',
  flagged boolean not null default false,
  flag_reason text,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0
);
comment on table intel.ask_message is 'One question or answer. An answer stores the tools called and the rows they returned (what the answer is based on).';
create index ask_message_ix1 on intel.ask_message (tenant_id, session_id, created_at);
alter table intel.ask_message enable row level security;
alter table intel.ask_message force row level security;
create policy tenant_isolation on intel.ask_message
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table intel.ai_ranking (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  company_id uuid not null references kernel.company(id),
  computed_at timestamptz not null default now(),
  model text,
  items jsonb not null,
  unique (tenant_id, company_id)
);
comment on table intel.ai_ranking is 'The order the AI layer gave the top open findings, with a one-line reason each; used while fresh, otherwise the deterministic rank_score decides.';
alter table intel.ai_ranking enable row level security;
alter table intel.ai_ranking force row level security;
create policy tenant_isolation on intel.ai_ranking
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
