-- Messaging channels keep no data of their own: the messages and their outcome are recorded by the kernel
-- (kernel.notification) and the gateway keys by the credential store. The schema exists so the plugin has a place to
-- hold gateway delivery receipts when those are received.
create schema if not exists plg_messaging;
comment on schema plg_messaging is 'Messaging channels plugin';
