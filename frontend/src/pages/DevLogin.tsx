// SPDX-License-Identifier: AGPL-3.0-or-later
/** Development-only sign-in: pick a synthetic user from the demo institution. */
import { Alert, Button, Heading, Spinner, Table, Text, View } from "@instructure/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { ApiError, apiFetch, type DevUser } from "../api";
import { useAuth } from "../auth";
import { TableScroll } from "../components/TableScroll";

export const DEMO_INSTITUTION = "demo-university";

const ROLE_LABELS: Record<string, string> = {
  student: "Student",
  lecturer: "Course staff",
  course_admin: "Course admin",
  issuer_manager: "Issuer manager",
  dept_admin: "Department admin",
  inst_admin: "Institution admin",
};

export function DevLogin() {
  const { setToken } = useAuth();
  const navigate = useNavigate();
  const users = useQuery({
    queryKey: ["dev-users"],
    queryFn: () => apiFetch<DevUser[]>(`/dev/institutions/${DEMO_INSTITUTION}/users`, null),
    retry: false,
  });
  const login = useMutation({
    mutationFn: (userId: string) =>
      apiFetch<{ token: string }>("/dev/login", null, {
        method: "POST",
        body: JSON.stringify({ institution: DEMO_INSTITUTION, user_id: userId }),
      }),
    onSuccess: (data) => {
      setToken(data.token);
      navigate("/");
    },
  });

  return (
    <View as="main" padding="large" maxWidth="60rem" margin="0 auto" display="block">
      <Heading level="h1" margin="0 0 small">
        Development sign-in
      </Heading>
      <Alert variant="warning" margin="0 0 medium">
        This page exists only in development. Real users open OpenCredential from Canvas. Every
        person listed here is synthetic.
      </Alert>
      {users.isPending && <Spinner renderTitle="Loading demo users" />}
      {users.isError && (
        <Alert variant="error">
          {users.error instanceof ApiError && users.error.problem.status === 404
            ? "Development sign-in is not available. Load the demo data with `oc seed`, or open OpenCredential from Canvas."
            : "Could not load demo users."}
        </Alert>
      )}
      {users.data && (
        <TableScroll>
        <Table caption="Demo users">
          <Table.Head>
            <Table.Row>
              <Table.ColHeader id="name">Name</Table.ColHeader>
              <Table.ColHeader id="roles">Roles</Table.ColHeader>
              <Table.ColHeader id="action">Action</Table.ColHeader>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {users.data.map((u) => (
              <Table.Row key={u.id}>
                <Table.Cell>{u.display_name ?? "Unnamed user"}</Table.Cell>
                <Table.Cell>
                  <Text>{u.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</Text>
                </Table.Cell>
                <Table.Cell>
                  <Button
                    onClick={() => login.mutate(u.id)}
                    interaction={login.isPending ? "disabled" : "enabled"}
                  >
                    Sign in as {u.display_name ?? "user"}
                  </Button>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        </TableScroll>
      )}
      {login.isError && <Alert variant="error" margin="medium 0 0">Sign-in failed.</Alert>}
    </View>
  );
}
