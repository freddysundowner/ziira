/**
 * The frontend SDK: the only thing modules import from outside their own folder (plus other
 * modules' public.ts). Enforced by ESLint (eslint.config.js), like ziira.sdk on the backend.
 */
export { api, ApiError, errorMessage, type Schemas, unwrap } from "./api";
export { toast } from "./notify";
export { type AvailableChannel, channelOptions, useChannels } from "./channels";
export { formatDate, getDisplayTimeZone, humanise, monthStart, money, percent, quantity, setDisplayTimeZone, subscribeDisplayTimeZone, today } from "./format";
export { orNull, useFormState } from "./form";
export { iconFor } from "./icons";
export { usePagedList } from "./query";
export { addModuleTranslations, LANGUAGES, setLanguage, useTranslation } from "./i18n";
export { profileFor, SIDEBAR, TILL_PAGES, type ProfileId, type SidebarPlan } from "./kindProfile";
export { AREA_IDS, type AreaId, defineModule, MENU_GROUPS, type MenuGroup, type MenuItem, type ModuleDefinition, type PageRoute, type SlotContribution, type SlotProps } from "./module";
export { ModulesProvider, Slot, SlotContent, useAccess, useActiveModules, useSlot } from "./modules";
export { type ActiveContribution, activeModules, type NavItem, slotContributions, visibleMenu, visibleRoutes } from "./registry";
export {
  AREA_DEFINITIONS, areaEntryPath, areaMembers, areaPages, buildNavigation, isSingle, itemsOfSection, type NavArea, type Navigation, placeOf, type Placement, type SidebarEntry,
} from "./areas";
export { setNavBadge, setNavFlag, useNavBadges } from "./navFlags";
export { useCompanies, useCompany, useCurrency, useDisplayTimeZone } from "./organisation";
export { type Theme, useTheme } from "./theme";
export {
  type Edition, type EditionStep, EDITION_KEY, hasLanded, landingTarget, orderedGroups, progress, setLanded, useEdition, useEditionChoices, visibleSteps,
} from "./edition";
export { SessionProvider, useCan, useSession } from "./session";
export * from "./ui";
export { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
export { CustomFields, CustomFieldsForm, saveCustomValues, useCustomFieldDefs } from "./customFields/CustomFields";
export { type CustomFieldDef, type CustomFieldProblem, type CustomValues, displayValue, toFormValues, toPayload, validateCustomValues, visibleFields } from "./customFields/logic";
export { Attachments } from "./attachments/Attachments";
export { type AttachedFile, formatBytes } from "./attachments/logic";
export { BackupCodes } from "./mfa/BackupCodes";
export { TwoStepSetup } from "./mfa/TwoStepSetup";
export { useCountdown } from "./mfa/useCountdown";
export * from "./mfa/helpers";
export { readStored, writeStored } from "./storage";
