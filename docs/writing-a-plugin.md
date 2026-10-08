# Writing a plugin

A plugin adds a capability without changing any module. See `ziira/plugins/catalog_stats`.

## Folder

```
ziira/plugins/<name>/
  manifest.toml        kind = "plugin", requires = [...]
  migrations/          0001_init.up.sql / .down.sql, creating schema plg_<name>
  events.py            @subscribe handlers (optional)
  api/routes.py        router mounted at the manifest's api_prefix (optional)
  README.md
```

## Rules

- Use only `ziira.sdk` and other units' `public.py`.
- Keep all tables in your own schema `plg_<name>`; enable and force row-level security on them.
- Declare permissions in the manifest.
- Handlers run inside the publisher's transaction: keep them small. An exception rolls back the
  original operation, so only raise to block an operation deliberately.

## Third-party plugins (later)

A plugin packaged separately registers itself in its own `pyproject.toml`:

```toml
[project.entry-points."ziira.units"]
my_plugin = "my_company.ziira_my_plugin"
```

The registry discovers it on start. In 1.0 only plugins built and signed by Ziira are installed.

## Lifecycle

```bash
ziira install <name>                # creates plg_<name>, registers permissions
ziira enable <tenant> <name>
ziira disable <tenant> <name>       # data kept
ziira uninstall <name>              # refused while any tenant has it enabled
```
