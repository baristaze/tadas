import { createBrowserRouter, Outlet } from "react-router-dom";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SignInPage } from "../features/sign_in/SignInPage";
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
  {
    element: <AuthenticatedShell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <TasksPage /> },
      { path: "/settings", element: <SettingsPage /> },
    ],
  },
]);
