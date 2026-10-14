import { api, unwrap, useQuery, useTranslation } from "@/sdk";

/** A function that turns a user id into a name. The user list needs another permission: without it ids are shortened. */
export function useUserNames(): (id: string | null | undefined) => string {
  const { t } = useTranslation("kernel");
  const users = useQuery({ queryKey: ["users"], retry: false, meta: { silent: true }, queryFn: () => unwrap(api.GET("/api/v1/users")) });
  const names = new Map((users.data ?? []).map((u) => [u.id, u.full_name]));
  return (id) => (id ? names.get(id) ?? t("dsr.userShort", { id: id.slice(0, 6) }) : "—");
}
