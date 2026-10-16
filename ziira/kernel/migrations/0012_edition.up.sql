-- The business's edition (what it chose when it joined, or switched to later) and its first-steps progress.
alter table kernel.tenant add column edition text not null default 'full';
alter table kernel.tenant add column onboarding_done text[] not null default '{}';
alter table kernel.tenant add column onboarding_dismissed boolean not null default false;
comment on column kernel.tenant.edition is 'Named bundle of units chosen at registration (editions.toml)';
