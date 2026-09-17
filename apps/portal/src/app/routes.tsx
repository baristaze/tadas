import { createBrowserRouter, Outlet } from "react-router-dom";
import { HomePage } from "../features/home/HomePage";
import { SignInPage } from "../features/sign_in/SignInPage";
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
    children: [{ path: "/", element: <HomePage /> }],
  },
]);
