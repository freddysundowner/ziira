
/** A band above the findings list. Contributions receive { companyId: string }. Used by Connected systems to explain that its checks stay quiet where Ziira Core covers the same ground. */
export const FINDINGS_BANNER = "intel.findings.banner";

/** Panels at the bottom of the Today page (the Daily summary module adds how the business is doing). */
export const TODAY_PANELS = "intel.today.panels";

/** Window event that opens the floating Ask Ziira panel (the panel lives in the shell's `shell.floating` slot). */
export const ASK_ZIIRA_OPEN_EVENT = "ziira:ask-open";

/** Open the floating Ask Ziira panel, optionally with a question to send. Does nothing when Ask Ziira is not available to the person. */
export function openAskZiira(question?: string): void {
  window.dispatchEvent(new CustomEvent(ASK_ZIIRA_OPEN_EVENT, { detail: { question } }));
}
