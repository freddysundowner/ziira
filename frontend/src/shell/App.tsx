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

import { BillingLink } from "./BillingNotice";
import { ErrorBoundary } from "./ErrorBoundary";
import { ForgotPassword } from "./ForgotPassword";
import { Home } from "./Home";
import { Layout } from "./Layout";
import { MfaSetupRequired } from "./MfaSetupRequired";
import { NotFound } from "./NotFound";
import { Register } from "./Register";
import { ResetPassword } from "./ResetPassword";
import { SignIn } from "./SignIn";
import { ConfirmEmail } from "./ConfirmEmail";
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

/** One lazy component per page loader, kept for the life of the app: switching an add-on on or off rebuilds the route list, and a
 *  fresh `lazy()` per rebuild would remount every page (the layout vanishes behind the loader and the scroll position is lost). */
const lazyPages = new WeakMap<object, ReturnType<typeof lazy>>();
function pageFor(load: Parameters<typeof lazy>[0]) {
  let page = lazyPages.get(load);
  if (!page) { page = lazy(load); lazyPages.set(load, page); }
  return page;
}

function ModuleRoutes() {
  const modules = useActiveModules();
  const access = useAccess();
  const routes = useMemo(
    () => visibleRoutes(modules, access).map((r) => ({ path: r.path, Page: pageFor(r.page) })),
    [modules, access],
  );
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          {routes.map(({ path, Page }) => <Route key={path} path={path} element={<Page />} />)}
          <Route path="/billing" element={<BillingLink />} />
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
  if (status === "mfa-setup") return <MfaSetupRequired />;
  if (status === "signed-out") {
    return (
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/register/verify" element={<VerifyRegistration />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
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

/** The business app: its own sign-in and session, only for the businesses' people. */
function BusinessApp() {
  return (
    <SessionProvider>
      <ErrorBoundary>
        <Gate />
      </ErrorBoundary>
      <Toaster />
    </SessionProvider>
  );
}

// Platform staff use a separate app at /operator with its own sign-in and session; it loads only when opened.
const OperatorApp = lazy(() => import("@/operator/OperatorApp"));
// The public booking page a business shares with its clients: no sign-in, no business session.
const PublicBookingPage = lazy(() => import("@/modules/bookings/booking-page/PublicBookingPage"));
// The page a customer opens from a repair estimate link: no sign-in, no business session.
const PublicApprovalPage = lazy(() => import("@/modules/jobs/approval/PublicApprovalPage"));
// The page an insurer or other payer opens from an estimate link to answer each line: no sign-in, no business session.
const PublicResponsePage = lazy(() => import("@/modules/claims/approval/PublicResponsePage"));

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/confirm-email" element={<ConfirmEmail />} />
          <Route path="/book/:slug" element={<Suspense fallback={<Loading />}><ErrorBoundary><PublicBookingPage /></ErrorBoundary></Suspense>} />
          <Route path="/job-approval/:token" element={<Suspense fallback={<Loading />}><ErrorBoundary><PublicApprovalPage /></ErrorBoundary></Suspense>} />
          <Route path="/claim-response/:token" element={<Suspense fallback={<Loading />}><ErrorBoundary><PublicResponsePage /></ErrorBoundary></Suspense>} />
          <Route path="/operator/*" element={<Suspense fallback={<Loading />}><ErrorBoundary><OperatorApp /></ErrorBoundary></Suspense>} />
          <Route path="*" element={<BusinessApp />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

