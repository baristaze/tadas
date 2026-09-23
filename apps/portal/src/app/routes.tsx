import { createBrowserRouter, Outlet } from "react-router-dom";
import { BillingPage } from "../features/billing/BillingPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SignInPage } from "../features/sign_in/SignInPage";
import { SignUpPage } from "../features/sign_up/SignUpPage";
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

export const router = createBrowserRouter([
  { path: "/sign-in", element: <SignInPage />, errorElement: <RouteError /> },
  { path: "/sign-up", element: <SignUpPage />, errorElement: <RouteError /> },
  {
    element: <AuthenticatedShell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <TasksPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "/settings/billing", element: <BillingPage /> },
    ],
  },
]);
