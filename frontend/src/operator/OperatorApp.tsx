/**
 * The operator console (`/operator`): a separate small app for platform staff. It has its own sign-in (email and password,
 * then a code when the platform requires a second factor), its own session that never mixes with a business session, no business menu, and it is loaded only when someone
 * opens `/operator`, so the business app's bundle does not carry it.
 */
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ErrorState, Spinner, Toaster, useTranslation } from "@/sdk";

import { ChangePasswordGate } from "./ChangePasswordGate";
import { Layout } from "./Layout";
import { useOperatorMe } from "./me";
import { OperatorSessionProvider, useOperator } from "./session";
import { SignInPage } from "./SignInPage";
import { StepUpProvider } from "./stepUp";
import { addOperatorTranslations } from "./translations";

addOperatorTranslations();

const UnitsPage = lazy(() => import("./pages/UnitsPage"));
const BusinessesPage = lazy(() => import("./pages/BusinessesPage"));
const BusinessPage = lazy(() => import("./pages/BusinessPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const SubscribersPage = lazy(() => import("./pages/subscribers/SubscribersPage"));
const SubscriberPage = lazy(() => import("./pages/subscribers/SubscriberPage"));
const PlansPage = lazy(() => import("./pages/plans/PlansPage"));
const PlansTab = lazy(() => import("./pages/plans/PlansTab"));
const AddonsTab = lazy(() => import("./pages/plans/AddonsTab"));
const CouponsTab = lazy(() => import("./pages/plans/CouponsTab"));
const PlanEditorPage = lazy(() => import("./pages/plans/PlanEditorPage"));
const BillingPage = lazy(() => import("./pages/billing/BillingPage"));
const InvoicesTab = lazy(() => import("./pages/billing/InvoicesTab"));
const RequestsTab = lazy(() => import("./pages/billing/RequestsTab"));
const SettingsTab = lazy(() => import("./pages/billing/SettingsTab"));
const LicencesPage = lazy(() => import("./pages/licences/LicencesPage"));
const AiPage = lazy(() => import("./pages/ai/AiPage"));
const HealthPage = lazy(() => import("./pages/HealthPage"));
const OperatorsPage = lazy(() => import("./pages/OperatorsPage"));
const WebsitePage = lazy(() => import("./pages/WebsitePage"));
const EmailPage = lazy(() => import("./pages/EmailPage"));
const ChatBotPage = lazy(() => import("./pages/ChatBotPage"));
const PlatformSettingsPage = lazy(() => import("./pages/PlatformSettingsPage"));
const AccountPage = lazy(() => import("./pages/AccountPage"));
const SetupPage = lazy(() => import("./pages/SetupPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));
const BackupsPage = lazy(() => import("./pages/BackupsPage"));
const MailLogPage = lazy(() => import("./pages/MailLogPage"));
const PaymentMethodsPage = lazy(() => import("./pages/PaymentMethodsPage"));
const PaymentAttemptsPage = lazy(() => import("./pages/PaymentAttemptsPage"));

function Loading() {
  const { t } = useTranslation("operator");
  return <div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("loading")}</div>;
}

/** Signed out: the sign-in screen, whatever address was asked for. Signed in: the console. */
export function Gate() {
  const { signedIn } = useOperator();
  if (!signedIn) return <SignInPage />;
  return (
    <StepUpProvider>
      <Console />
    </StepUpProvider>
  );
}

/** The console itself, or only the change-password screen while a temporary password is still in use. */
function Console() {
  const me = useOperatorMe();
  if (me.isPending) return <Loading />;
  if (me.data?.must_change_password) return <ChangePasswordGate />;
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="subscribers" element={<SubscribersPage />} />
          <Route path="subscribers/:code" element={<SubscriberPage />} />
          <Route path="plans" element={<PlansPage />}>
            <Route index element={<PlansTab />} />
            <Route path="addons" element={<AddonsTab />} />
            <Route path="coupons" element={<CouponsTab />} />
          </Route>
          <Route path="plans/new" element={<PlanEditorPage />} />
          <Route path="plans/edit/:code" element={<PlanEditorPage />} />
          <Route path="billing" element={<BillingPage />}>
            <Route index element={<Navigate to="invoices" replace />} />
            <Route path="invoices" element={<InvoicesTab />} />
            <Route path="requests" element={<RequestsTab />} />
            {/* These two tabs became screens of their own (Revenue > Payment methods, System > Payment attempts). */}
            <Route path="payment-attempts" element={<Navigate to="/operator/payment-attempts" replace />} />
            <Route path="payment-methods" element={<Navigate to="/operator/payment-methods" replace />} />
            <Route path="settings" element={<SettingsTab />} />
          </Route>
          <Route path="payment-methods" element={<PaymentMethodsPage />} />
          <Route path="payment-attempts" element={<PaymentAttemptsPage />} />
          <Route path="licences" element={<LicencesPage />} />
          <Route path="units" element={<UnitsPage />} />
          {/* The old Businesses pages: bookmarks and links still land on the subscribers pages. */}
          <Route path="businesses" element={<BusinessesPage />} />
          <Route path="businesses/:code" element={<BusinessPage />} />
          <Route path="ai" element={<AiPage />} />
          <Route path="health" element={<HealthPage />} />
          <Route path="backups" element={<BackupsPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="mail-log" element={<MailLogPage />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="operators" element={<OperatorsPage />} />
          <Route path="website" element={<WebsitePage />} />
          <Route path="email" element={<EmailPage />} />
          <Route path="chat-bot" element={<ChatBotPage />} />
          <Route path="settings" element={<PlatformSettingsPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="*" element={<ErrorState title="404" message="This page is not in the console." />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function OperatorApp() {
  return (
    <OperatorSessionProvider>
      <Gate />
      <Toaster />
    </OperatorSessionProvider>
  );
}
