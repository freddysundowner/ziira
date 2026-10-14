import { expect, type Locator, type Page } from "@playwright/test";

/** Choose an option in the app's searchable picker (the `Combobox`): open it, type, click the match. */
export async function pick(page: Page, picker: Locator, search: string, option: string | RegExp = search) {
  await picker.click();
  const box = page.getByRole("textbox", { name: "Search", exact: true });
  await box.fill(search);
  const choice = page.getByRole("option", { name: option }).first();
  await choice.click();
  await expect(box).toBeHidden();
}

/** A success or error toast with this text. */
export const toastWith = (page: Page, text: string | RegExp) => page.getByText(text).first();

/** The drawer or dialog currently open. */
export const drawer = (page: Page) => page.getByRole("dialog");

/** Today as YYYY-MM-DD in the browser's zone. */
export const todayISO = () => new Date().toLocaleDateString("en-CA");

/** Match a form label exactly, with or without the required star (a plain `getByLabel("Code")` also matches "Tax authority code"). */
export const lbl = (text: string) => new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\*?$`);
