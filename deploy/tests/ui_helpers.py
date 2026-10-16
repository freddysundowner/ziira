from installer.ui import UI


def quiet_ui(**kw):  # type: ignore[no-untyped-def]
    return UI(color=False, interactive=False, **kw)
