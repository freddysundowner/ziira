-- The platform's chat bot (docs/ai.md section 15): one connected number answered by the website assistant's brain.
-- Platform level, no business: everything here is master data. Secrets are Fernet tokens (write-only, never returned or
-- logged). Visitors are kept as keyed hashes plus a masked display; their words live at most seven days.

create table master.chat_bot (
  id int primary key default 1 check (id = 1),
  provider text not null,
  config jsonb not null default '{}',
  secrets_encrypted text,
  connection jsonb not null default '{}',
  token_hash text unique,
  enabled boolean not null default false,
  key_tested_at timestamptz,
  key_tested_ok boolean,
  texts jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  updated_by text
);
comment on table master.chat_bot is 'The one chat bot of the platform. secrets_encrypted: {api_key, webhook_secret} as a Fernet token. connection: provider references (never a secret). token_hash: SHA-256 of the random token in the public inbound address.';

create table master.chat_event (
  event_id text primary key,
  received_at timestamptz not null default now(),
  sender_hash text,
  outcome text not null default 'received'
);
create index chat_event_received_ix on master.chat_event (received_at desc);
comment on table master.chat_event is 'De-duplication of deliveries by the provider''s event id, and the outcome counters (answered, unknown, opted_out, failed ...). No message text.';

create table master.chat_sender (
  sender_hash text primary key,
  masked text not null,
  lang text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  welcomed_at timestamptz,
  opted_out_at timestamptz
);
comment on table master.chat_sender is 'One person who wrote to the bot: a keyed hash of the number and a masked display (+254...123). The number itself is never kept here.';

create table master.chat_turn (
  id bigserial primary key,
  sender_hash text not null references master.chat_sender(sender_hash) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  body text not null,
  created_at timestamptz not null default now()
);
create index chat_turn_sender_ix on master.chat_turn (sender_hash, id desc);
comment on table master.chat_turn is 'The last few turns of a conversation (for context only), scrubbed of personal data. Purged after seven days.';

create table master.chat_handoff (
  id uuid primary key default gen_random_uuid(),
  sender_hash text not null,
  sender_masked text not null,
  snippet text,
  status text not null default 'open' check (status in ('open', 'done')),
  created_at timestamptz not null default now(),
  done_at timestamptz,
  done_by text
);
create index chat_handoff_status_ix on master.chat_handoff (status, created_at desc);
comment on table master.chat_handoff is 'A person asked to talk to a human. The snippet is their last message with personal data removed; it is cleared after seven days.';

create table master.chat_outbox (
  id bigserial primary key,
  event_id text not null,
  kind text not null check (kind in ('compute', 'send', 'notify_support', 'test')),
  sender_hash text,
  to_encrypted text,
  payload_encrypted text,
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
  attempts int not null default 0,
  next_at timestamptz not null default now(),
  result text,
  created_at timestamptz not null default now(),
  done_at timestamptz,
  unique (event_id, kind)
);
create index chat_outbox_due_ix on master.chat_outbox (next_at) where status = 'pending';
comment on table master.chat_outbox is 'Replies to send after the delivery was answered (the model took too long), and hand-off notices. The recipient and the text are Fernet tokens and are cleared as soon as the job ends.';
