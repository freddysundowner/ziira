-- The master database (ziira_master) is created by POSTGRES_DB in docker-compose.yml.
-- Each tenant's own database and login are created by `ziira create-tenant`,
-- using the superuser ziira (ZIIRA_TENANT_SERVER_URL). Nothing else is needed here.
select 1;
