import { api, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

/** Explains how a phone number is read: with the company's calling code when we may see it, else generally. */
export function usePhoneHint(companyId: string): string {
  const { t } = useTranslation("crm");
  const canSee = useCan("settings.manage");
  const settings = useQuery({
    enabled: canSee && !!companyId, queryKey: ["company-settings", companyId], retry: false, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId } } })),
  });
  const code = settings.data?.phone_country_code;
  return code ? t("phoneHintCode", { code }) : t("phoneHint");
}
