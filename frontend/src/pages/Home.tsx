// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  Alert,
  Button,
  Heading,
  List,
  Spinner,
  Text,
  View,
} from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiFetch, apiSend, problemText, type Course, type Me } from "../api";
import { useAuth } from "../auth";
import { AppLink } from "../components/AppLink";
import { ConfirmButton } from "../components/ConfirmButton";
import { Nav, roleFlags, useMe } from "../components/Page";

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
  useEffect(() => {
    document.title = "Home · Badges";
  }, []);
  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => apiFetch<Me>("/api/v1/learners/me", token),
  });

  if (me.isPending)
    return <Spinner renderTitle="Loading your profile" margin="large" />;
  if (me.isError)
    return (
      <View as="main" padding="large" display="block">
        <Alert variant="error">
          Your session has expired. Choose Badges in your Canvas course menu
          again.
        </Alert>
      </View>
    );

  const user = me.data;
  const staff = roleFlags(user).isStaff;
  // Staff elsewhere who opened Badges in a course where they have no role (often a Canvas
  // administrator looking around): the staff links are about their other courses, not this one.
  const outsider =
    staff && !!user.launch_course && user.launch_course.roles.length === 0;
  const staffCourses = [
    ...new Set(
      user.memberships
        .filter(
          (m) =>
            m.scope_type === "course" && m.role !== "student" && m.scope_name,
        )
        .map((m) => m.scope_name as string),
    ),
  ];
  return (
    <View
      as="div"
      padding="large"
      maxWidth="60rem"
      margin="0 auto"
      display="block"
    >
      <a href="#main-content" className="oc-skip-link">
        Skip to main content
      </a>
      <Nav />
      <main id="main-content" tabIndex={-1} style={{ outline: "none" }}>
        <Heading level="h1" margin="0 0 small">
          Welcome, {user.display_name ?? "there"}
        </Heading>
        <Text as="p">{user.institution.name}</Text>
        {user.canvas_admin_without_access && (
          <CanvasAdminSetup admins={user.institution_admins ?? []} />
        )}
        {user.launch_course && <CourseContext course={user.launch_course} />}
        {user.institution.is_demo && (
          <Alert variant="info" margin="small 0">
            You are using demonstration data. Nothing here is a real badge.
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
          {outsider
            ? `You have no role in ${user.launch_course?.title ?? "this course"}, so there is nothing for you to manage here. The links above are for the courses where you are staff${staffCourses.length ? `: ${staffCourses.join(", ")}` : ""}.`
            : staff
              ? "Use the links above to create, review and award badges, and to see your students' progress."
              : 'Use the links above to see the badges in your courses and your progress. In "My badges" you can download, share and add your badges to LinkedIn.'}
        </Text>
        {user.session_method === "dev" && (
          <Button margin="medium 0 0" onClick={() => setToken(null)}>
            Sign out
          </Button>
        )}
      </main>
    </View>
  );
}

/**
 * A Canvas administrator who opens Badges sees no administration until someone gives them a
 * role here: Canvas roles never carry over (ADR-0013). Say so, and say who can help, rather
 * than leave them on a page that only reads "No course role".
 */
function CanvasAdminSetup({ admins }: { admins: string[] }) {
  return (
    <View
      as="section"
      aria-labelledby="oc-admin-setup"
      display="block"
      margin="medium 0"
    >
      <Alert variant="info">
        <Heading level="h2" id="oc-admin-setup" margin="0 0 x-small">
          Setting up badges
        </Heading>
        <Text as="p">
          You are a Canvas administrator, but you do not have an administrator
          role in Badges yet. Canvas roles do not carry over, so that only the
          people your institution chooses can change badge settings.
        </Text>
        {admins.length > 0 ? (
          <Text as="p">
            Ask one of the Badges administrators to give you a role under
            Administration, then Staff roles: {admins.join(", ")}.
          </Text>
        ) : (
          <Text as="p">
            Nobody is a Badges administrator yet. Whoever runs the Badges
            service makes the first one, now that you have opened Badges once
            (step 6 of the Canvas set-up guide). Tell them the email address you
            use in Canvas. After that, administrators give roles to others under
            Administration, then Staff roles.
          </Text>
        )}
      </Alert>
    </View>
  );
}

/** Where the user launched from and what they can do there (spec §4.1, §20 Phase 2). */
function CourseContext({
  course,
}: {
  course: NonNullable<Me["launch_course"]>;
}) {
  const roles = course.roles.length
    ? course.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")
    : "No course role";
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
        {course.course_code ? `${course.course_code} · ` : ""}Canvas course{" "}
        {course.canvas_course_id} · Your role: <strong>{roles}</strong>
      </Text>
      {course.status !== "active" &&
        (course.view === "lecturer" ? (
          <ActivateCourse courseId={course.id} />
        ) : (
          <Alert variant="info" margin="small 0">
            Course staff have not switched on badges for this course yet.
          </Alert>
        ))}
      {course.view === "lecturer" && course.status === "active" && (
        <BadgeTeamsToggle courseId={course.id} />
      )}
      {course.view === "lecturer" ? (
        <Text as="p">
          <AppLink to={`/courses/${course.id}/progress`}>
            Course progress
          </AppLink>
          {" · "}
          <AppLink to="/badges">Badges for this course</AppLink>
        </Text>
      ) : (
        <Text as="p">
          <AppLink to="/me/progress">
            Badges in my courses and my progress
          </AppLink>
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
    mutationFn: () =>
      apiSend<{ status: string }>(
        `/api/v1/courses/${courseId}/activate`,
        token,
        "POST",
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
  return (
    <Alert variant="info" margin="small 0">
      <Text as="p">
        Badges are not switched on for this course yet. Switch them on to read
        students&apos; progress from Canvas now and then regularly (every 30
        minutes for badges based on Canvas activity; badges that staff award
        only need the class list, refreshed every 6 hours). You can switch them
        off again at any time; issued badges are not affected.
      </Text>
      <Button
        color="primary"
        onClick={() => activate.mutate()}
        interaction={activate.isPending ? "disabled" : "enabled"}
      >
        Switch on badges for this course
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
  const isAdmin = roleFlags(useMe().data).isAdmin;
  const [confirming, setConfirming] = useState(false);
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => apiFetch<Course[]>("/api/v1/courses", token),
  });
  const course = courses.data?.find((c) => c.id === courseId);
  const set = useMutation({
    mutationFn: (enabled: boolean) =>
      apiSend<Course>(`/api/v1/courses/${courseId}/badge-teams`, token, "PUT", {
        enabled,
      }),
    onSuccess: () => {
      setConfirming(false);
      qc.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  if (!course) return null;
  const on = !!course.badge_teams;
  return (
    <View as="div" margin="small 0">
      <Heading level="h3" margin="0 0 x-small">
        Badge teams
      </Heading>
      <Text as="p">
        {on
          ? "On: each badge here is edited and awarded only by its owner, the colleagues they add on its Team tab, and administrators."
          : "Off: every member of staff in this course can edit and award every badge. Switch badge teams on in a course many staff share, such as a library or CPD course."}
      </Text>
      {!on && !confirming && (
        <Button onClick={() => setConfirming(true)}>
          Switch badge teams on
        </Button>
      )}
      {on && isAdmin && (
        <ConfirmButton
          label="Switch badge teams off"
          consequence="Switch badge teams off? Every member of staff in this course will be able to edit and award every badge again. The teams stay named, and apply again if badge teams are switched back on."
          confirmLabel="Switch off"
          cancelLabel="Keep badge teams on"
          busy={set.isPending}
          onConfirm={() => set.mutate(false)}
        />
      )}
      {on && !isAdmin && (
        <Text as="p" size="small">
          Ask an administrator if badge teams need switching off.
        </Text>
      )}
      {confirming && (
        <Alert variant="warning" margin="small 0">
          <Text as="p">
            Colleagues will immediately lose the ability to edit or award badges
            they do not own until the owner adds them to the badge's team. Only
            an administrator can switch badge teams off again.
          </Text>
          <Button
            color="primary"
            margin="small small 0 0"
            interaction={set.isPending ? "disabled" : "enabled"}
            onClick={() => set.mutate(true)}
          >
            Switch on
          </Button>
          <Button margin="small 0 0 0" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </Alert>
      )}
      {set.isError && (
        <Text as="p" color="danger">
          {problemText(set.error)}
        </Text>
      )}
    </View>
  );
}
