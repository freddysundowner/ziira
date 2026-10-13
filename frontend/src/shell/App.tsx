/**
 * The shell: always present, like the backend kernel. Sign-in, layout, router, and the module
 * registry. Pages come only from active modules, filtered by the user's permissions.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useMemo } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { allModules } from "@/modules";
import {
  addModuleTranslations,
  ModulesProvider,
  SessionProvider,
  useAccess,
  useActiveModules,
  useSession,
  useTranslation,
  visibleRoutes,
} from "@/sdk";

import { Home } from "./Home";
import { Layout } from "./Layout";
import { SignIn } from "./SignIn";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } });
addModuleTranslations(allModules);

function ModuleRoutes() {
  const { t } = useTranslation();
  const modules = useActiveModules();
  const access = useAccess();
  const routes = useMemo(
    () => visibleRoutes(modules, access).map((r) => ({ path: r.path, Page: lazy(r.page) })),
    [modules, access],
  );
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">{t("loading")}</p>}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          {routes.map(({ path, Page }) => <Route key={path} path={path} element={<Page />} />)}
          <Route path="*" element={<p className="text-sm text-slate-500">{t("notFound")}</p>} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function Gate() {
  const { status } = useSession();
  const { t } = useTranslation();
  if (status === "loading") return <p className="p-6 text-sm text-slate-500">{t("loading")}</p>;
  if (status === "signed-out") return <SignIn />;
  return (
    <ModulesProvider all={allModules}>
      <ModuleRoutes />
    </ModulesProvider>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionProvider>
          <Gate />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
