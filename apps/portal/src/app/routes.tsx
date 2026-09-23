import { createBrowserRouter, Navigate, Outlet, useLocation } from "react-router-dom";
import { BillingPage } from "../features/billing/BillingPage";
import { NewOrgPage } from "../features/new_org/NewOrgPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { CallbackPage } from "../features/sign_in/CallbackPage";
import { DevSignInPage } from "../features/sign_in/DevSignInPage";
import { LoginPage } from "../features/sign_in/LoginPage";
import { TasksPage } from "../features/tasks/TasksPage";
import { RealtimeProvider } from "../realtime/RealtimeProvider";
import { RequireAuth } from "./RequireAuth";
import { RouteError } from "./RouteError";

function AuthenticatedShell() {
  return (
    <RequireAuth>
      <RealtimeProvider>
        <Outlet />
      </RealtimeProvider>
    </RequireAuth>
  );
}

/** An address an older build linked to: it goes on to the sign-in, keeping
 * the page it was sent from. */
function Moved({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={to} replace state={location.state} />;
}

export const router = createBrowserRouter([
  // The identity provider's "initiate login" address: it starts a sign-in at once.
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  { path: "/login/dev", element: <DevSignInPage />, errorElement: <RouteError /> },
  { path: "/auth/callback", element: <CallbackPage />, errorElement: <RouteError /> },
  { path: "/sign-in", element: <Moved to="/login" />, errorElement: <RouteError /> },
  { path: "/sign-up", element: <Moved to="/login?screen_hint=sign-up" />, errorElement: <RouteError /> },
  {
    element: <AuthenticatedShell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <TasksPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "/settings/billing", element: <BillingPage /> },
      { path: "/orgs/new", element: <NewOrgPage /> },
    ],
  },
]);
