import { createRootRoute, Outlet, redirect } from "@tanstack/react-router";
import { TanStackRouterDevtools } from "@tanstack/router-devtools";

const PUBLIC_ROUTES = ["/login", "/register"];

export const Route = createRootRoute({
  beforeLoad: ({ location }) => {
    const token = localStorage.getItem("access_token");
    const isPublic = PUBLIC_ROUTES.includes(location.pathname);
    if (!token && !isPublic) {
      throw redirect({ to: "/login" });
    }
    if (token && isPublic) {
      throw redirect({ to: "/" });
    }
  },
  component: () => (
    <>
      <Outlet />
      <TanStackRouterDevtools />
    </>
  ),
});
