import { api, Alert, Combobox, unwrap, useQuery, useTranslation } from "@/sdk";

/** Choose a person from the business's users. The server refuses anyone who cannot answer findings for the branch. */
export default function PersonPicker({ value, onChange, clearable }: { value: string; onChange: (userId: string) => void; clearable?: boolean }) {
  const { t } = useTranslation("intel");
  const users = useQuery({ queryKey: ["users"], queryFn: () => unwrap(api.GET("/api/v1/users")), staleTime: 60_000 });
  if (users.error) return <Alert tone="warn">{t("peopleUnavailable", { message: users.error.message })}</Alert>;
  const options = (users.data ?? []).filter((u) => u.status !== "disabled").map((u) => ({ value: u.id, label: u.full_name, hint: u.email ?? u.phone ?? undefined }));
  return <Combobox value={value} onChange={onChange} options={options} clearable={clearable} placeholder={users.isLoading ? t("loading") : t("choosePerson")} disabled={users.isLoading} />;
}
