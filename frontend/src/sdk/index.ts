/**
 * The frontend SDK: the only thing modules import from outside their own folder (plus other
 * modules' public.ts). Enforced by ESLint (eslint.config.js), like ziira.sdk on the backend.
 */
export { api, ApiError, errorMessage, type Schemas, unwrap } from "./api";
export { toast } from "./notify";
export { formatDate, humanise, monthStart, money, percent, quantity, today } from "./format";
export { orNull, useFormState } from "./form";
export { iconFor } from "./icons";
export { usePagedList } from "./query";
export { addModuleTranslations, LANGUAGES, setLanguage, useTranslation } from "./i18n";
export { defineModule, MENU_GROUPS, type MenuGroup, type MenuItem, type ModuleDefinition, type PageRoute, type SlotContribution, type SlotProps } from "./module";
export { ModulesProvider, Slot, SlotContent, useAccess, useActiveModules, useSlot } from "./modules";
export { type ActiveContribution, activeModules, slotContributions, visibleMenu, visibleRoutes } from "./registry";
export { useCompanies, useCompany, useCurrency } from "./organisation";
export { type Theme, useTheme } from "./theme";
export { SessionProvider, useCan, useSession } from "./session";
export * from "./ui";
export { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
