# Website theme (navy re-skin) status

Done 2026-10-19 by the website theme agent. Not committed.

* Re-skinned and re-laid-out `site/` to the owner's homepage mockup: navy theme, Inter (self-hosted), gradient pill buttons, 1160px container, sticky blurred header, light and dark bands. Details: `docs/marketing-site.md` "Design system".
* Home (`site/src/components/Home.astro`, `content/home.ts`) follows the mockup's section order with our own content. Inner pages use the same header, footer, page head and section styles through shared tokens (no per-page changes).
* New logo SVGs and favicon; old fonts removed.

## Mockup to our content
hero > hero + example card; logo strip > "Works with" (real integrations); problem (quote + icon cards) > "same day" quote + three example alerts; intelligence (steps + evidence panel) > "What happens every day" + example summary; architecture > Run it / Watch it / Connect it; capabilities > app tiles; use cases > five "what you can do" cards + kinds of business; integrations > "Keep the system you already use"; trust > "What you can rely on"; pricing > pricing teaser; FAQ, CTA, footer > ours. Ours with no mockup section (one-platform diagram, screenshots, three steps, comparison table) got the same band styling.

## Placeholder / not matched
* Logo SVG is an approximation of the supplied PNG (dots mark simplified).
* The mockup's fake dashboard is replaced by the real Today screenshot (small text inside it).
* Mockup partner names, numbers, copy: not used.
* OG share images (`src/pages/og`) still use the old teal card; restyle when wanted.
* Known unrelated test failures at the time: `tests/complete-guide.test.ts` and `platform-build.test.ts` (catalogue-count 128 vs 123, from other agents' edits to `checks.catalog.json`/`checks.plain.json`).
