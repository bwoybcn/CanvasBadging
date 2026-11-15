// SPDX-License-Identifier: AGPL-3.0-or-later
import { InstUISettingsProvider, canvas } from "@instructure/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AuthProvider, readLaunchSession, useAuth } from "./auth";
import { StaffOnly } from "./components/Page";
import { AdminHome } from "./pages/admin/AdminHome";
import { Audit } from "./pages/admin/Audit";
import { Credentials } from "./pages/admin/Credentials";
import { InstitutionSettings } from "./pages/admin/Institution";
import { Issuers } from "./pages/admin/Issuers";
import { AreaReviewPage, Areas, CoursePlacement, StaffRoles } from "./pages/admin/People";
import { Privacy } from "./pages/admin/Privacy";
import { Reconciliation } from "./pages/admin/Reconciliation";
import { Reports } from "./pages/admin/Reports";
import { Templates } from "./pages/admin/Templates";
import { AdminPolicy } from "./pages/AdminPolicy";
import { Awards } from "./pages/Awards";
import { BadgeDetail } from "./pages/BadgeDetail";
import { BadgeList, ReviewQueue } from "./pages/BadgeList";
import { CourseProgress } from "./pages/CourseProgress";
import { CreateBadge } from "./pages/CreateBadge";
import { CredentialDetail } from "./pages/CredentialDetail";
import { DevLogin } from "./pages/DevLogin";
import { Home } from "./pages/Home";
import { Keeping } from "./pages/Keeping";
import { MyCredentials } from "./pages/MyCredentials";
import { MyProgress } from "./pages/MyProgress";

function RequireSession({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  return token ? children : <Navigate to="/dev-login" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/dev-login" element={<DevLogin />} />
      <Route path="/launch" element={<Navigate to="/" replace />} />
      {(
        [
          ["/", <Home />],
          ["/badges", <StaffOnly><BadgeList /></StaffOnly>],
          ["/badges/new", <StaffOnly><CreateBadge /></StaffOnly>],
          ["/badges/:id", <StaffOnly><BadgeDetail /></StaffOnly>],
          ["/badges/:id/edit", <StaffOnly><CreateBadge /></StaffOnly>],
          ["/reviews", <StaffOnly><ReviewQueue /></StaffOnly>],
          ["/awards", <StaffOnly><Awards /></StaffOnly>],
          ["/courses/:id/progress", <StaffOnly><CourseProgress /></StaffOnly>],
          ["/me/progress", <MyProgress />],
          ["/me/credentials", <MyCredentials />],
          ["/me/credentials/:id", <CredentialDetail />],
          ["/me/keeping", <Keeping />],
          ["/admin", <AdminHome />],
          ["/admin/institution", <InstitutionSettings />],
          ["/admin/policy", <AdminPolicy />],
          ["/admin/issuers", <Issuers />],
          ["/admin/areas", <Areas />],
          ["/admin/courses", <CoursePlacement />],
          ["/admin/roles", <StaffRoles />],
          ["/admin/review", <AreaReviewPage />],
          // "Departments and roles" was one long page until it was split into the four above.
          ["/admin/people", <Navigate to="/admin/areas" replace />],
          ["/admin/templates", <Templates />],
          ["/admin/credentials", <Credentials />],
          ["/admin/reports", <Reports />],
          ["/admin/audit", <Audit />],
          ["/admin/privacy", <Privacy />],
          ["/admin/reconciliation", <Reconciliation />],
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
  const [token] = useState(() => readLaunchSession());
  return (
    <Providers token={token}>
      <BrowserRouter basename="/app">
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
