# API schema class renames (service modules)

Two pydantic classes with the same name make the OpenAPI generator prefix both (`ziira__modules__x__api__schemas__Name`),
which breaks web code that uses the short name. The new modules' classes were renamed to be unique. `tests/test_openapi_names.py`
fails if any schema name outside the frozen `LEGACY` set (older duplicates, already used by their long names) is prefixed.

| Old name (python class / schema key) | New name |
|---|---|
| bookings `CancelIn` | `BookingCancelIn` |
| bookings `SeriesOut` | `BookingSeriesOut` |
| jobs `EventOut` | `JobEventOut` |
| jobs `NoteIn` | `JobNoteIn` |
| jobs `SettingsOut` | `JobSettingsOut` |
| jobs `SettingsUpdate` | `JobSettingsUpdate` |
| jobs `StatusIn` | `JobStatusIn` |
| jobs `TemplateOut` | `JobTemplateOut` |
| timebilling `EntryOut` | `TimeBillingEntryOut` |
| timebilling `ExpenseIn` | `TimeBillingExpenseIn` |
| timebilling `ExpenseOut` | `TimeBillingExpenseOut` |
| timebilling `ManualLineIn` | `TimeBillingManualLineIn` |
| timebilling `NoteIn` | `TimeBillingNoteIn` |
| timebilling `SettingsOut` | `TimeBillingSettingsOut` |
| timebilling `SettingsUpdate` | `TimeBillingSettingsUpdate` |

Web: use `Schemas["JobEventOut"]` instead of `Schemas["ziira__modules__jobs__api__schemas__EventOut"]` (same pattern for the rest).
The unprefixed names of older classes (`SeriesOut`, `EventOut`, `EntryOut`, ...) are unique again.
