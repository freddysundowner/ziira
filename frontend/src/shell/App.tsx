/**
 * The shell: always present, like the backend kernel. Sign-in, layout, router, and the module
 * registry. Pages come only from active modules, filtered by the user's permissions.
 */
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useMemo } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { allModules } from "@/modules";
import {
  addModuleTranslations,
  ApiError,
  ErrorState,
  errorMessage,
  ModulesProvider,
  SessionProvider,
  Spinner,
  toast,
  Toaster,
  useAccess,
  useActiveModules,
  useSession,
  useTranslation,
  visibleRoutes,
} from "@/sdk";

import { ErrorBoundary } from "./ErrorBoundary";
import { Home } from "./Home";
import { Layout } from "./Layout";
import { NotFound } from "./NotFound";
import { Register } from "./Register";
import { SignIn } from "./SignIn";
import { VerifyRegistration } from "./VerifyRegistration";

/**
 * One place decides how failures look. A failed save shows a message (unless the screen shows its own: meta.silent); a
 * failed background refresh of data already on screen stays quiet; a missing record or permission is the page's job.
 */
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.state.data !== undefined && !(error instanceof ApiError && error.status === 0)) toast(errorMessage(error), "bad");
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _v, _c, mutation) => {
      if (!mutation.meta?.silent) toast(errorMessage(error), "bad");
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});
addModuleTranslations(allModules);

function Loading() {
  const { t } = useTranslation();
  return <div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("loading")}</div>;
}

function ModuleRoutes() {
  const modules = useActiveModules();
  const access = useAccess();
  const routes = useMemo(
    () => visibleRoutes(modules, access).map((r) => ({ path: r.path, Page: lazy(r.page) })),
    [modules, access],
  );
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          {routes.map(({ path, Page }) => <Route key={path} path={path} element={<Page />} />)}
          <Route path="/register/*" element={<Navigate to="/" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function Gate() {
  const { status, retry } = useSession();
  const { t } = useTranslation();
  if (status === "loading") return <Loading />;
  if (status === "unreachable") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <ErrorState title={t("unreachable.title")} message={t("unreachable.hint")} onRetry={retry} />
      </div>
    );
  }
  if (status === "signed-out") {
    return (
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/register/verify" element={<VerifyRegistration />} />
        <Route path="*" element={<SignIn />} />
      </Routes>
    );
  }
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
          <ErrorBoundary>
            <Gate />
          </ErrorBoundary>
          <Toaster />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

