-- The gemini provider keeps no data of its own: consent, usage and the call log are Intelligence's (intel schema).
-- The schema exists so the plugin has a place to hold provider-specific records later, like every plugin.
create schema if not exists plg_ai_gemini;
comment on schema plg_ai_gemini is 'gemini AI provider plugin';
