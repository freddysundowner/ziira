-- Audit entries record the device the user signed in on. Sessions identify devices by the id the
-- client sent at sign-in (any text, e.g. a browser UUID), so the column becomes text.
alter table kernel.audit_log alter column device_id type text using device_id::text;
