// SPDX-License-Identifier: AGPL-3.0-or-later
import { Alert, Button, Checkbox, Heading, List, Spinner, Text, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, apiSend, problemText, type Course, type Me } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { Nav } from "../components/Page";

const ROLE_LABELS: Record<string, string> = {
  student: "Student",
  lecturer: "Course staff",
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
      <Nav />
      <Heading level="h1" margin="0 0 small">
        Welcome, {user.display_name ?? "there"}
      </Heading>
      <Text as="p">{user.institution.name}</Text>
      {user.launch_course && <CourseContext course={user.launch_course} />}
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
        Use the links above to see your badges and credentials, create and review micro-credentials, or confirm
        awards. Students can download, share and add their credentials to LinkedIn from "My credentials".
      </Text>
      {user.session_method === "dev" && (
        <Button margin="medium 0 0" onClick={() => setToken(null)}>
          Sign out
        </Button>
      )}
    </View>
  );
}

/** Where the user launched from and what they can do there (spec §4.1, §20 Phase 2). */
function CourseContext({ course }: { course: NonNullable<Me["launch_course"]> }) {
  const roles = course.roles.length ? course.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ") : "No course role";
  return (
    <View
      as="section"
      aria-labelledby="oc-course-context"
      display="block"
      padding="medium"
      margin="medium 0"
      borderWidth="small"
      borderRadius="medium"
      data-testid="course-context"
    >
      <Heading level="h2" id="oc-course-context" margin="0 0 x-small">
        {course.title}
      </Heading>
      <Text as="p">
        {course.course_code ? `${course.course_code} · ` : ""}Canvas course {course.canvas_course_id} · Your role:{" "}
        <strong>{roles}</strong>
      </Text>
      {course.status !== "active" &&
        (course.view === "lecturer" ? (
          <ActivateCourse courseId={course.id} />
        ) : (
          <Alert variant="info" margin="small 0">
            Course staff have not switched on micro-credentials for this course yet.
          </Alert>
        ))}
      {course.view === "lecturer" && course.status === "active" && <BadgeTeamsToggle courseId={course.id} />}
      {course.view === "lecturer" ? (
        <Text as="p">
          <AppLink to={`/courses/${course.id}/progress`}>Course progress</AppLink>
          {" · "}
          <AppLink to="/badges">Badges for this course</AppLink>
        </Text>
      ) : (
        <Text as="p">
          <AppLink to="/me/progress">My badges and progress</AppLink>
        </Text>
      )}
    </View>
  );
}

/** Switch micro-credentials on for the launched course: it then reads Canvas progress on a schedule. */
function ActivateCourse({ courseId }: { courseId: string }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const activate = useMutation({
    mutationFn: () => apiSend<{ status: string }>(`/api/v1/courses/${courseId}/activate`, token, "POST"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
  return (
    <Alert variant="info" margin="small 0">
      <Text as="p">
        Micro-credentials are not switched on for this course yet. Switch them on to read students&apos; progress from
        Canvas now and then regularly (every 30 minutes for badges based on Canvas activity; badges that staff award
        only need the class list, refreshed every 6 hours). You can switch them off again at any time; issued credentials are not
        affected.
      </Text>
      <Button color="primary" onClick={() => activate.mutate()} interaction={activate.isPending ? "disabled" : "enabled"}>
        Switch on micro-credentials for this course
      </Button>
      {activate.isError && (
        <Text as="p" color="danger">
          {problemText(activate.error)}
        </Text>
      )}
    </Alert>
  );
}

/** Badge teams: in a course many staff share (a library or CPD course), each badge is edited and
 * awarded only by its own team. Lecturers can switch this on; only administrators switch it off. */
function BadgeTeamsToggle({ courseId }: { courseId: string }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetch<Course[]>("/api/v1/courses", token) });
  const course = courses.data?.find((c) => c.id === courseId);
  const set = useMutation({
    mutationFn: (enabled: boolean) =>
      apiSend<Course>(`/api/v1/courses/${courseId}/badge-teams`, token, "PUT", { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["courses"] }),
  });
  if (!course) return null;
  return (
    <View as="div" margin="small 0">
      <Checkbox
        label="Badge teams: each badge here is edited and awarded only by its owner and the colleagues they add"
        checked={!!course.badge_teams}
        disabled={set.isPending}
        onChange={(e) => set.mutate(e.target.checked)}
      />
      {set.isError && (
        <Text as="p" color="danger">
          {problemText(set.error)}
        </Text>
      )}
    </View>
  );
}
