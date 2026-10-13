/**
 * The frontend SDK: the only thing modules import from outside their own folder (plus other
 * modules' public.ts). Enforced by ESLint (eslint.config.js), like ziira.sdk on the backend.
 */
export { api, errorMessage, type Schemas } from "./api";
export { addModuleTranslations, LANGUAGES, setLanguage, useTranslation } from "./i18n";
export { defineModule, type MenuItem, type ModuleDefinition, type PageRoute, type SlotContribution, type SlotProps } from "./module";
export { ModulesProvider, Slot, SlotContent, useAccess, useActiveModules, useSlot } from "./modules";
export { type ActiveContribution, activeModules, slotContributions, visibleMenu, visibleRoutes } from "./registry";
export { useCompanies } from "./organisation";
export { SessionProvider, useCan, useSession } from "./session";
export { Button, Card, ErrorText, Field, Input, PageHeader, Select, Table } from "./ui";
export { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
