// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * When the wizard's lists of Canvas modules and assignments were read, and a way to read them
 * again (round 3, finding M2). A course whose live badges use no Canvas data is only read now and
 * then, so its lists can be days old; lists older than an hour are refreshed on their own.
 */
import { Alert, Button, Text, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiFetch, apiSend, problemText, type SyncState } from "../api";

/** Lists older than this are refreshed when the requirements step opens. */
const STALE_MS = 60 * 60 * 1000;
const POLL_MS = 2000;
const POLL_LIMIT = 20;

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function CanvasRefresh({
  courseId,
  token,
}: {
  courseId: string;
  token: string | null;
}) {
  const qc = useQueryClient();
  const state = useQuery({
    queryKey: ["sync", courseId],
    queryFn: () =>
      apiFetch<SyncState>(`/api/v1/courses/${courseId}/sync`, token),
  });
  const refresh = useMutation({
    mutationFn: async ({ automatic }: { automatic: boolean }) => {
      // What Canvas reading looked like before this click, read now rather than from the page
      // (which may be minutes old): only a run that started after it can be this one's result.
      let before: SyncState | undefined = state.data;
      try {
        before = await apiFetch<SyncState>(`/api/v1/courses/${courseId}/sync`, token);
      } catch {
        // Fall back to what the page already holds.
      }
      const succeededBefore = before?.last_success_at ?? null;
      const runBefore = before?.last_run?.started_at ?? null;
      try {
        await apiSend(`/api/v1/courses/${courseId}/sync`, token, "POST");
      } catch (e) {
        if (automatic) return "skipped" as const;
        throw e;
      }
      for (let i = 0; i < POLL_LIMIT; i++) {
        await wait(POLL_MS);
        const now = await apiFetch<SyncState>(
          `/api/v1/courses/${courseId}/sync`,
          token,
        );
        qc.setQueryData(["sync", courseId], now);
        if (now.last_success_at && now.last_success_at !== succeededBefore)
          return "done" as const;
        // An earlier failure is still the "last run" until this one starts: it says nothing
        // about this refresh, so it is not reported as this refresh failing.
        if (
          now.last_run?.status === "failed" &&
          (now.last_run.started_at ?? null) !== runBefore
        )
          return "failed" as const;
      }
      return "slow" as const;
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["modules", courseId] });
      void qc.invalidateQueries({ queryKey: ["assignments", courseId] });
    },
  });

  const started = useRef(false);
  useEffect(() => {
    if (started.current || !state.data) return;
    const last = state.data.last_success_at;
    if (!last || Date.now() - new Date(last).getTime() > STALE_MS) {
      started.current = true;
      refresh.mutate({ automatic: true });
    }
  }, [state.data, refresh]);

  const last = state.data?.last_success_at;
  const outcome = refresh.data;
  return (
    <View as="div" margin="0 0 small" display="block">
      <Text as="p" size="small">
        {refresh.isPending
          ? "Reading the course's modules and assignments from Canvas…"
          : last
            ? `Modules and assignments as read from Canvas on ${new Date(last).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}. Added something in Canvas just now? Refresh the lists.`
            : "This course has not been read from Canvas yet."}
      </Text>
      <Button
        size="small"
        onClick={() => refresh.mutate({ automatic: false })}
        interaction={refresh.isPending ? "disabled" : "enabled"}
      >
        Refresh from Canvas
      </Button>
      <div aria-live="polite">
        {outcome === "done" && !refresh.isPending && (
          <Alert variant="success" margin="small 0 0">
            The lists are up to date with Canvas.
          </Alert>
        )}
        {outcome === "failed" && (
          <Alert variant="warning" margin="small 0 0">
            Canvas could not be read just now, so the lists below may be out of
            date. Try again in a few minutes.
          </Alert>
        )}
        {outcome === "slow" && (
          <Alert variant="info" margin="small 0 0">
            Canvas is taking a while to answer. The lists will update when it
            does; you can carry on meanwhile.
          </Alert>
        )}
        {refresh.isError && (
          <Alert variant="warning" margin="small 0 0">
            {problemText(refresh.error)}
          </Alert>
        )}
      </div>
    </View>
  );
}
