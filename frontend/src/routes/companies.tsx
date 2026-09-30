import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/companies")({
  component: () => <Outlet />,
});
