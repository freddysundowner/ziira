/**
 * Translations: English and Swahili. The shell's strings are in the "shell" namespace; each module's
 * are in a namespace named after its unit, added from its manifest: t("products:menu").
 */
import i18n from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";

import en from "@/i18n/en.json";
import sw from "@/i18n/sw.json";

import type { ModuleDefinition } from "./module";
import { readStored, writeStored } from "./storage";

export const LANGUAGES = { en: "English", sw: "Kiswahili" } as const;
const LANGUAGE_KEY = "ziira.language";

void i18n.use(initReactI18next).init({
  resources: { en: { shell: en }, sw: { shell: sw } },
  lng: readStored(LANGUAGE_KEY) ?? "en",
  fallbackLng: "en",
  defaultNS: "shell",
  interpolation: { escapeValue: false },
});

export function addModuleTranslations(modules: readonly ModuleDefinition[]): void {
  for (const m of modules) {
    if (!m.translations) continue;
    i18n.addResourceBundle("en", m.unit, m.translations.en, true, true);
    i18n.addResourceBundle("sw", m.unit, m.translations.sw, true, true);
  }
}

export function setLanguage(language: keyof typeof LANGUAGES): void {
  writeStored(LANGUAGE_KEY, language);
  void i18n.changeLanguage(language);
}

export { i18n, useTranslation };
