-- The country a business operates in (ISO 3166 code), chosen at registration. It is data about the business, used to
-- offer sensible defaults; nothing in the platform treats any country specially.
alter table kernel.company add column country char(2) check (country is null or country ~ '^[A-Z]{2}$');
