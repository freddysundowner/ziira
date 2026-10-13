import { type FormEvent, useState } from "react";

import {
  api,
  Button,
  Card,
  ErrorText,
  errorMessage,
  Field,
  Input,
  PageHeader,
  Table,
  useMutation,
  useQuery,
  useQueryClient,
  useTranslation,
} from "@/sdk";

export default function UsersPage() {
  const { t } = useTranslation("kernel");
  const [creating, setCreating] = useState(false);
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: async () => (await api.GET("/api/v1/users")).data ?? [] });
  const create = useMutation({
    mutationFn: async (form: FormData) => {
      const value = (k: string) => (String(form.get(k) ?? "").trim() || null);
      const { data, error } = await api.POST("/api/v1/users", {
        body: { full_name: String(form.get("full_name")), email: value("email"), phone: value("phone"), password: value("password") },
      });
      if (!data) throw new Error(errorMessage(error));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      setCreating(false);
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate(new FormData(event.currentTarget));
  }

  return (
    <>
      <PageHeader title={t("users")} actions={<Button onClick={() => setCreating(!creating)}>{t("newUser")}</Button>} />
      {creating && (
        <Card title={t("newUser")}>
          <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
            <Field label={t("fullName")}><Input name="full_name" required /></Field>
            <Field label={t("email")}><Input name="email" type="email" /></Field>
            <Field label={t("phone")}><Input name="phone" /></Field>
            <Field label={t("password")}><Input name="password" type="password" minLength={8} /></Field>
            <div className="md:col-span-2">
              <ErrorText>{create.error?.message}</ErrorText>
              <Button type="submit" disabled={create.isPending}>{t("save")}</Button>
            </div>
          </form>
        </Card>
      )}
      <div className="mt-4">
        <Card>
          <Table
            rows={users.data ?? []}
            rowKey={(u) => u.id}
            empty={t("noUsers")}
            columns={[
              { header: t("fullName"), cell: (u) => u.full_name },
              { header: t("email"), cell: (u) => u.email ?? "—" },
              { header: t("phone"), cell: (u) => u.phone ?? "—" },
              { header: t("status"), cell: (u) => u.status },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
