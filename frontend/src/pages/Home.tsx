// SPDX-License-Identifier: AGPL-3.0-or-later
import { Alert, Button, Heading, List, Spinner, Text, View } from "@instructure/ui";
import { useQuery } from "@tanstack/react-query";

import { apiFetch, type Me } from "../api";
import { useAuth } from "../auth";

const ROLE_LABELS: Record<string, string> = {
  student: "Student",
  lecturer: "Lecturer",
  course_admin: "Course admin",
  issuer_manager: "Issuer manager",
  dept_admin: "Department admin",
  inst_admin: "Institution admin",
};

export function Home() {
  const { token, setToken } = useAuth();
  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => apiFetch<Me>("/api/v1/learners/me", token),
  });

  if (me.isPending) return <Spinner renderTitle="Loading your profile" margin="large" />;
  if (me.isError)
    return (
      <View as="main" padding="large" display="block">
        <Alert variant="error">Your session has expired. Open OpenCredential from Canvas again.</Alert>
      </View>
    );

  const user = me.data;
  return (
    <View as="main" padding="large" maxWidth="60rem" margin="0 auto" display="block">
      <Heading level="h1" margin="0 0 small">
        Welcome, {user.display_name ?? "there"}
      </Heading>
      <Text as="p">{user.institution.name}</Text>
      {user.institution.is_demo && (
        <Alert variant="info" margin="small 0">
          You are using demonstration data. Nothing here is a real credential.
        </Alert>
      )}
      <Heading level="h2" margin="medium 0 small">
        Your roles
      </Heading>
      <List>
        {user.memberships.map((m) => (
          <List.Item key={`${m.role}-${m.scope_id}`}>
            {ROLE_LABELS[m.role] ?? m.role}
            {m.scope_name ? ` in ${m.scope_name}` : ""}
          </List.Item>
        ))}
      </List>
      <Text as="p">
        Badge browsing, authoring and administration screens are added in the next stages of the
        build.
      </Text>
      {user.session_method === "dev" && (
        <Button margin="medium 0 0" onClick={() => setToken(null)}>
          Sign out
        </Button>
      )}
    </View>
  );
}
