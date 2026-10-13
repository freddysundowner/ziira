# Writing a plugin

A plugin adds a capability without changing any module. See `ziira/plugins/catalog_stats`.

## Folder

```
ziira/plugins/<name>/
  manifest.toml        kind = "plugin", requires = [...]
  migrations/          0001_init.up.sql / .down.sql, creating schema plg_<name>
  events.py            @subscribe handlers (optional)
  hooks.py             @validate / @provides: plug into other units' sockets (optional; declare under [extends])
  api/routes.py        router mounted at the manifest's api_prefix (optional)
  README.md
```

## Rules

- Use only `ziira.sdk` and other units' `public.py`.
- Keep all tables in your own schema `plg_<name>`; enable and force row-level security on them.
- Declare permissions in the manifest, give default roles theirs under `[roles]`, and protect every
  route with `Depends(require_permission("<name>.view"))`.
- `@subscribe` handlers run inside the publisher's transaction: keep them small. An exception rolls
  back the original operation, so only raise to block an operation deliberately.
- Slow or external work (webhooks, messages) goes in `@subscribe_after` handlers, which run after
  commit (via `ziira outbox-run`), are retried on failure, and must be safe to run twice.

- To block or extend another unit's action (validation hooks, extension points) see `docs/extending-units.md`.
- A plugin can add screens to the web app through slots; see `docs/frontend.md`.

## Third-party plugins (later)

A plugin packaged separately registers itself in its own `pyproject.toml`:

```toml
[project.entry-points."ziira.units"]
my_plugin = "my_company.ziira_my_plugin"
```

The registry discovers it on start. In 1.0 only plugins built and signed by Ziira are installed.

## Lifecycle

```bash
ziira install <name>                # offers it on the platform (master database)
ziira enable <tenant> <name>        # creates plg_<name> in that tenant's database
ziira disable <tenant> <name>       # data kept
ziira remove <tenant> <name>        # drops plg_<name> from that tenant's database (after disable)
ziira uninstall <name>              # refused while any tenant database still has it
```
