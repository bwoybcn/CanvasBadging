// SPDX-License-Identifier: AGPL-3.0-or-later
import { InstUISettingsProvider, canvas } from "@instructure/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AuthProvider, useAuth } from "./auth";
import { AdminPolicy } from "./pages/AdminPolicy";
import { Awards } from "./pages/Awards";
import { BadgeDetail } from "./pages/BadgeDetail";
import { BadgeList, ReviewQueue } from "./pages/BadgeList";
import { CourseProgress } from "./pages/CourseProgress";
import { CreateBadge } from "./pages/CreateBadge";
import { DevLogin } from "./pages/DevLogin";
import { Home } from "./pages/Home";
import { MyProgress } from "./pages/MyProgress";

function RequireSession({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  return token ? children : <Navigate to="/dev-login" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/dev-login" element={<DevLogin />} />
      {(
        [
          ["/", <Home />],
          ["/badges", <BadgeList />],
          ["/badges/new", <CreateBadge />],
          ["/badges/:id", <BadgeDetail />],
          ["/badges/:id/edit", <CreateBadge />],
          ["/reviews", <ReviewQueue />],
          ["/awards", <Awards />],
          ["/courses/:id/progress", <CourseProgress />],
          ["/me/progress", <MyProgress />],
          ["/admin/policy", <AdminPolicy />],
        ] as const
      ).map(([path, element]) => (
        <Route key={path} path={path} element={<RequireSession>{element}</RequireSession>} />
      ))}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function Providers({ children, token = null }: { children: ReactNode; token?: string | null }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1 } } }));
  return (
    <InstUISettingsProvider theme={canvas}>
      <QueryClientProvider client={client}>
        <AuthProvider initialToken={token}>{children}</AuthProvider>
      </QueryClientProvider>
    </InstUISettingsProvider>
  );
}

export default function App() {
  return (
    <Providers>
      <BrowserRouter basename="/app">
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
