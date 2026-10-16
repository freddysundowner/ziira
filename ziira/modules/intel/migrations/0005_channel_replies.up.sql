-- Replying by WhatsApp: the action log says which channel a decision came by, and a question typed to Ziira on a channel
-- waits here until the background worker (which holds no database transaction while it waits for the AI provider) has
-- answered it.
alter table intel.action_log add column channel text not null default 'app';
comment on column intel.action_log.channel is 'Where the decision was made: app, whatsapp or intelligence (an automatic action)';

create table intel.channel_question (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  user_id uuid not null references kernel.app_user(id),
  channel text not null,
  sender text not null,
  message_id text not null,
  question text not null,
  status text not null default 'pending' check (status in ('pending', 'answering', 'answered', 'failed')),
  answered_at timestamptz,
  unique (tenant_id, message_id)
);
comment on table intel.channel_question is 'A question a signed-in person typed to Ziira on a channel, waiting for its answer, which is sent back on the same channel.';
create index channel_question_ix1 on intel.channel_question (tenant_id, status, created_at);
alter table intel.channel_question enable row level security;
alter table intel.channel_question force row level security;
create policy tenant_isolation on intel.channel_question
  using (tenant_id = kernel.current_tenant()) with check (tenant_id = kernel.current_tenant());
