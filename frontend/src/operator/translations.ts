import { i18n } from "@/sdk/i18n";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";
import enPlatform from "./i18n/en.platform.json";
import swPlatform from "./i18n/sw.platform.json";
import enAi from "./i18n/en.ai.json";
import swAi from "./i18n/sw.ai.json";
import enWebsite from "./i18n/en.website.json";
import swWebsite from "./i18n/sw.website.json";
import enShell from "./i18n/en.shell.json";
import enChat from "./i18n/en.chat.json";
import swChat from "./i18n/sw.chat.json";
import swShell from "./i18n/sw.shell.json";

/** The console's words live in their own namespace ("operator"), added when the console loads. */
export function addOperatorTranslations(): void {
  i18n.addResourceBundle("en", "operator", en, true, true);
  i18n.addResourceBundle("sw", "operator", sw, true, true);
  i18n.addResourceBundle("en", "operator", enPlatform, true, true);
  i18n.addResourceBundle("sw", "operator", swPlatform, true, true);
  i18n.addResourceBundle("en", "operator", enAi, true, true);
  i18n.addResourceBundle("sw", "operator", swAi, true, true);
  i18n.addResourceBundle("en", "operator", enWebsite, true, true);
  i18n.addResourceBundle("sw", "operator", swWebsite, true, true);
  i18n.addResourceBundle("en", "operator", enShell, true, true);
  i18n.addResourceBundle("sw", "operator", swShell, true, true);
  i18n.addResourceBundle("en", "operator", enChat, true, true);
  i18n.addResourceBundle("sw", "operator", swChat, true, true);
}
