"""Starting points for the website's legal pages.

These are outlines, not legal advice. Each section holds a `TODO(legal)` line that the business must replace, and the
page opens with a note to remove once a lawyer has reviewed it: the publish check refuses a page that still contains
either, so a template can never go live by accident. No country, law or company is assumed in the outlines.
"""

LEGAL_SLUGS = ("privacy", "terms", "cookies", "refunds", "acceptable-use", "data-processing")

_NOTE = {
    "en": "> **Template: review with your lawyer.** Replace every TODO(legal) line and delete this note "
          "before publishing.",
    "sw": "> **Kiolezo: kikaguliwe na mwanasheria wako.** Badilisha kila mstari wa TODO(legal) na futa maelezo "
          "haya kabla ya kuchapisha.",
}
_TODO = {
    "en": "TODO(legal): write this section for your business and the places where you operate.",
    "sw": "TODO(legal): andika sehemu hii kwa ajili ya biashara yako na maeneo unapofanyia kazi.",
}

# slug -> (English title, Swahili title, [(English heading, Swahili heading), ...])
_OUTLINES: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "privacy": ("Privacy policy", "Sera ya faragha", [
        ("Who we are", "Sisi ni nani"), ("What personal data we collect", "Data binafsi tunayokusanya"),
        ("Why we use it and our legal basis", "Kwa nini tunaitumia na msingi wetu wa kisheria"),
        ("Who we share it with", "Tunayeishirikisha"), ("How long we keep it", "Tunaihifadhi kwa muda gani"),
        ("Your rights and how to use them", "Haki zako na jinsi ya kuzitumia"),
        ("How to contact us", "Jinsi ya kuwasiliana nasi")]),
    "terms": ("Terms of service", "Masharti ya huduma", [
        ("The service", "Huduma"), ("Accounts and who may use them", "Akaunti na wanaoruhusiwa kuzitumia"),
        ("Fees and payment", "Ada na malipo"), ("Your data", "Data yako"),
        ("Availability and support", "Upatikanaji na msaada"), ("Liability", "Dhima"),
        ("Ending the agreement", "Kumaliza makubaliano"), ("Changes to these terms", "Mabadiliko ya masharti haya")]),
    "cookies": ("Cookie policy", "Sera ya vidakuzi", [
        ("What cookies and similar tools are", "Vidakuzi na zana kama hizo ni nini"),
        ("The ones we use and why", "Tunavyotumia na kwa nini"),
        ("How to change your choice", "Jinsi ya kubadilisha chaguo lako")]),
    "refunds": ("Refund and cancellation policy", "Sera ya kurejesha pesa na kughairi", [
        ("Cancelling your subscription", "Kughairi usajili wako"), ("When we refund", "Tunaporejesha pesa"),
        ("How to ask", "Jinsi ya kuomba")]),
    "acceptable-use": ("Acceptable use policy", "Sera ya matumizi yanayokubalika", [
        ("What you may not do", "Usichoruhusiwa kufanya"),
        ("What happens if the rules are broken", "Kinachotokea sheria zikivunjwa"),
        ("Reporting a problem", "Kuripoti tatizo")]),
    "data-processing": ("Data processing terms", "Masharti ya usindikaji wa data", [
        ("Roles: who decides and who processes", "Majukumu: nani anaamua na nani anasindika"),
        ("What data, for how long and for what", "Data gani, kwa muda gani na kwa nini"),
        ("Security measures", "Hatua za usalama"), ("Sub-processors", "Wasindikaji wasaidizi"),
        ("Help with requests and breaches", "Msaada kwa maombi na uvunjifu"),
        ("Returning or deleting data", "Kurudisha au kufuta data")]),
}


def starter(slug: str, locale: str) -> dict[str, str] | None:
    """A draft for a legal page: its title and Markdown body, in English or Swahili (English for other languages)."""
    outline = _OUTLINES.get(slug)
    if outline is None:
        return None
    lang = "sw" if locale.split("-")[0] == "sw" else "en"
    title = outline[1] if lang == "sw" else outline[0]
    pick = 1 if lang == "sw" else 0
    sections = "\n\n".join(f"## {heading[pick]}\n\n{_TODO[lang]}" for heading in outline[2])
    return {"slug": slug, "locale": locale, "title": title, "body_md": f"{_NOTE[lang]}\n\n{sections}\n"}


def starters(locale: str) -> list[dict[str, str]]:
    return [s for slug in LEGAL_SLUGS if (s := starter(slug, locale)) is not None]
