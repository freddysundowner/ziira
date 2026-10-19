-- Ziira Core · schema 'timebilling' · professional services: capped fees, write-downs and partner review, expense
-- categories and markup defaults, missed-time nudges and approval reminders, recurring engagements with checklists.

-- fee types: a capped fee bills time at the rate card but never more than the cap
alter table timebilling.project drop constraint if exists project_billing_mode_check;
alter table timebilling.project add constraint project_billing_mode_check
  check (billing_mode in ('time_and_materials', 'fixed_fee', 'capped_fee', 'retainer'));
alter table timebilling.project add column fee_cap numeric(18,2) check (fee_cap is null or fee_cap > 0);
comment on column timebilling.project.fee_cap is 'Capped-fee projects: the most that time on this project can be billed in total.';

-- settings
alter table timebilling.setting
  add column partner_review boolean not null default false,
  add column partner_review_above numeric(18,2) not null default 0 check (partner_review_above >= 0),
  add column default_markup_percent numeric(7,2) not null default 0 check (default_markup_percent between 0 and 1000),
  add column receipt_required_above numeric(18,2) check (receipt_required_above is null or receipt_required_above >= 0),
  add column nudge_minutes integer not null default 0 check (nudge_minutes between 0 and 1440),
  add column nudge_hour integer not null default 9 check (nudge_hour between 0 and 23),
  add column work_days smallint[] not null default '{1,2,3,4,5}',
  add column approval_reminder_days integer not null default 2 check (approval_reminder_days between 0 and 60),
  add column approval_escalate_days integer not null default 5 check (approval_escalate_days between 0 and 60);
comment on column timebilling.setting.nudge_minutes is 'A working day with less than this logged gets a reminder the next morning (0 = no reminders).';
comment on column timebilling.setting.work_days is 'ISO weekdays (1 = Monday) people are expected to log time.';

alter table timebilling.staff
  add column approver_id uuid references kernel.app_user(id),
  add column away_until date,
  add column nudges boolean not null default true;
comment on column timebilling.staff.approver_id is 'Who is asked first to approve this person''s weeks (anyone with the permission still may).';

alter table timebilling.client_terms
  add column expense_markup_percent numeric(7,2) check (expense_markup_percent is null or expense_markup_percent between 0 and 1000);

-- expenses (disbursements)
alter table timebilling.expense add column category text;
alter table timebilling.expense add column written_off boolean not null default false;
alter table timebilling.entry add column written_off boolean not null default false;
comment on column timebilling.entry.written_off is 'Billed at nothing on an issued review (a write-off with a reason on the review line); the time itself is never changed.';

-- retainers: monthly-fee drafts
alter table timebilling.retainer
  add column bill_day integer not null default 1 check (bill_day between 1 and 28),
  add column auto_draft boolean not null default true;

-- invoice reviews: write-downs, partner review, narrative
alter table timebilling.invoice_batch
  add column review_status text not null default 'none' check (review_status in ('none', 'requested', 'approved', 'changes_requested')),
  add column review_requested_by uuid references kernel.app_user(id),
  add column review_requested_at timestamptz,
  add column review_by uuid references kernel.app_user(id),
  add column review_at timestamptz,
  add column review_note text,
  add column narrative text;
alter table timebilling.invoice_batch_line
  add column list_amount numeric(18,2),
  add column list_minutes integer,
  add column write_down_reason text,
  add column automatic boolean not null default false;
comment on column timebilling.invoice_batch_line.list_amount is 'What the line is worth before any write-down; amount is what is billed. NULL on old rows (= amount).';
update timebilling.invoice_batch_line set list_amount = amount, list_minutes = minutes where list_amount is null;

-- recurring engagements and their dated tasks
create table timebilling.recurrence (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  project_id uuid not null references timebilling.project(id),
  name text not null,
  frequency text not null check (frequency in ('monthly', 'quarterly', 'annual')),
  due_day integer not null check (due_day between 1 and 31),
  due_month integer check (due_month is null or due_month between 1 and 12),
  lead_days integer not null default 14 check (lead_days between 0 and 120),
  starts_on date not null,
  ends_on date,
  assignee_id uuid references kernel.app_user(id),
  checklist jsonb not null default '[]',
  active boolean not null default true,
  check (ends_on is null or ends_on >= starts_on)
);
comment on table timebilling.recurrence is 'Work that comes back every month, quarter or year (a monthly bookkeeping close, an annual return).';
alter table timebilling.recurrence enable row level security;
alter table timebilling.recurrence force row level security;
create policy tenant_isolation on timebilling.recurrence
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.engagement_task (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  project_id uuid not null references timebilling.project(id),
  recurrence_id uuid references timebilling.recurrence(id),
  name text not null,
  period text,
  due_on date not null,
  status text not null default 'open' check (status in ('open', 'done', 'skipped')),
  assignee_id uuid references kernel.app_user(id),
  items jsonb not null default '[]',
  note text,
  done_at timestamptz,
  done_by uuid references kernel.app_user(id)
);
comment on table timebilling.engagement_task is 'One dated piece of work for an engagement, with a checklist: made from a recurrence or added by hand.';
alter table timebilling.engagement_task enable row level security;
alter table timebilling.engagement_task force row level security;
create policy tenant_isolation on timebilling.engagement_task
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
create unique index engagement_task_one_per_period on timebilling.engagement_task (recurrence_id, period)
  where recurrence_id is not null;
create index engagement_task_due on timebilling.engagement_task (company_id, due_on) where status = 'open';
create index engagement_task_project on timebilling.engagement_task (project_id);

-- reminders already sent (one row per kind of reminder per subject and day, so a reminder is sent once)
create table timebilling.nudge_log (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  kind text not null,
  subject_id uuid not null,
  user_id uuid not null,
  day date not null,
  unique (kind, subject_id, user_id, day)
);
alter table timebilling.nudge_log enable row level security;
alter table timebilling.nudge_log force row level security;
create policy tenant_isolation on timebilling.nudge_log
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- example rates shipped by an industry pack: shown, but never used to price work until the business makes them real
alter table timebilling.rate add column example boolean not null default false;
comment on column timebilling.rate.example is 'An example row from a pack: ignored when pricing, until the business confirms it.';

-- engagement templates, activity lists and standard wording (data a business edits; packs ship starting points)
create table timebilling.engagement_template (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  description text,
  billing_mode text not null default 'time_and_materials'
    check (billing_mode in ('time_and_materials', 'fixed_fee', 'capped_fee', 'retainer')),
  budget_minutes integer check (budget_minutes is null or budget_minutes > 0),
  frequency text check (frequency is null or frequency in ('monthly', 'quarterly', 'annual')),
  due_day integer check (due_day is null or due_day between 1 and 31),
  due_month integer check (due_month is null or due_month between 1 and 12),
  lead_days integer not null default 14 check (lead_days between 0 and 120),
  checklist jsonb not null default '[]',
  milestones jsonb not null default '[]',
  source text not null default 'business',
  active boolean not null default true,
  unique (company_id, name)
);
alter table timebilling.engagement_template enable row level security;
alter table timebilling.engagement_template force row level security;
create policy tenant_isolation on timebilling.engagement_template
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.activity (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  name text not null,
  group_name text,
  billable boolean not null default true,
  sort_order integer not null default 0,
  source text not null default 'business',
  active boolean not null default true,
  unique (company_id, name)
);
alter table timebilling.activity enable row level security;
alter table timebilling.activity force row level security;
create policy tenant_isolation on timebilling.activity
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.snippet (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  created_by uuid references kernel.app_user(id),
  updated_at timestamptz,
  updated_by uuid references kernel.app_user(id),
  company_id uuid not null references kernel.company(id),
  kind text not null check (kind in ('invoice_note', 'engagement_note')),
  name text not null,
  language text not null default 'en',
  body text not null,
  source text not null default 'business',
  active boolean not null default true,
  unique (company_id, kind, name, language)
);
alter table timebilling.snippet enable row level security;
alter table timebilling.snippet force row level security;
create policy tenant_isolation on timebilling.snippet
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

-- sample data from an industry pack: the recipe the pack shipped, and what loading it made (so it can be removed)
create table timebilling.sample_recipe (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  recipe jsonb not null,
  unique (company_id, pack)
);
alter table timebilling.sample_recipe enable row level security;
alter table timebilling.sample_recipe force row level security;
create policy tenant_isolation on timebilling.sample_recipe
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());

create table timebilling.sample_item (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references kernel.tenant(id),
  created_at timestamptz not null default now(),
  company_id uuid not null references kernel.company(id),
  pack text not null,
  item_type text not null,
  item_id uuid not null,
  label text,
  unique (item_type, item_id)
);
alter table timebilling.sample_item enable row level security;
alter table timebilling.sample_item force row level security;
create policy tenant_isolation on timebilling.sample_item
  using (tenant_id = kernel.current_tenant())
  with check (tenant_id = kernel.current_tenant());
