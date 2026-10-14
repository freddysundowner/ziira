drop table if exists kernel.privacy_request;
alter table kernel.notification drop column if exists redacted_at;
