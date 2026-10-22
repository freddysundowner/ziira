-- A till can ask for a short reference when a product needs one (a prescription number, an authorisation note). It is a
-- note typed at the till, kept on the line it belongs to. It is not a clinical record: no patient data beyond what the
-- cashier chooses to type, and the business decides the wording.
alter table pos.sale_line add column reference text check (reference is null or length(reference) <= 120);
comment on column pos.sale_line.reference is 'Optional reference note typed at the till for a product that asks for one';
