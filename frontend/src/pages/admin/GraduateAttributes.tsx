// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The institution's graduate attributes: the qualities its badges develop, such as Confidence
 * or Digital Fluency. Authors tag badges with them; issued badges carry them, so anyone checking
 * a badge sees which attributes it develops. Editing the list never changes a badge already
 * published.
 */
import { Alert, Button, Flex, Heading, Text, TextInput, View } from "@instructure/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch, apiSend, type GraduateAttribute, type GraduateAttributeIn } from "../../api";
import { useAuth } from "../../auth";
import { AppLink } from "../../components/AppLink";
import { LimitedTextArea } from "../../components/Fields";
import { ErrorAlert, Loading } from "../../components/Page";
import { AdminPage } from "./AdminPage";

const MAX = 20;

interface Row {
  key: string | null; // null until saved: the server makes one from the name
  name: string;
  description: string;
  framework: string;
  url: string;
}

const toRow = (a: GraduateAttribute): Row => ({
  key: a.key,
  name: a.name,
  description: a.description ?? "",
  framework: a.framework ?? "",
  url: a.url ?? "",
});

/** The rows as the API takes them; rows with no name are left out. */
export function toAttributesIn(rows: Row[]): GraduateAttributeIn[] {
  return rows
    .filter((r) => r.name.trim())
    .map((r) => ({
      key: r.key,
      name: r.name.trim(),
      description: r.description.trim() || null,
      framework: r.framework.trim() || null,
      url: r.url.trim() || null,
    }));
}

export function GraduateAttributes() {
  const { token } = useAuth();
  const q = useQuery({
    queryKey: ["graduate-attributes"],
    queryFn: () => apiFetch<GraduateAttribute[]>("/api/v1/admin/graduate-attributes", token),
  });
  return (
    <AdminPage title="Graduate attributes" instOnly>
      <Text as="p">
        The qualities your badges help students develop, in your institution&apos;s own words. Authors tick the ones a badge
        develops, and every badge awarded from it names them, so anyone checking it can see them. Changing this list never
        changes a badge that is already published.
      </Text>
      <Text as="p">
        To start from the University of Liverpool&apos;s attributes and the templates written around them, use the
        template packs on <AppLink to="/admin/templates">Badge templates</AppLink>.
      </Text>
      {q.isPending && <Loading what="graduate attributes" />}
      {q.isError && <ErrorAlert error={q.error} />}
      {q.data && <Editor key={q.data.map((a) => a.key).join()} initial={q.data} />}
    </AdminPage>
  );
}

function Editor({ initial }: { initial: GraduateAttribute[] }) {
  const { token } = useAuth();
  const qc = useQueryClient();
  const [rows, setRows] = useState<Row[]>(initial.map(toRow));
  const change = (i: number, k: keyof Row) => (_e: unknown, v: string) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = useMutation({
    mutationFn: () =>
      apiSend<GraduateAttribute[]>("/api/v1/admin/graduate-attributes", token, "PUT", {
        attributes: toAttributesIn(rows),
      }),
    onSuccess: (d) => {
      qc.setQueryData(["graduate-attributes"], d);
      qc.invalidateQueries({ queryKey: ["categories"] });
    },
  });
  return (
    <View as="div" maxWidth="40rem">
      {rows.length === 0 && <Text as="p">No graduate attributes yet.</Text>}
      {rows.map((r, i) => (
        <View
          key={r.key ?? `new-${i}`}
          as="fieldset"
          borderWidth="small"
          borderRadius="medium"
          padding="small"
          margin="0 0 small"
          display="block"
        >
          <Heading level="h2" margin="0 0 x-small">
            {r.name.trim() || `New attribute ${i + 1}`}
          </Heading>
          <TextInput maxLength={80} renderLabel="Name" value={r.name} onChange={change(i, "name")} />
          <LimitedTextArea
            maxLength={600}
            label="What it means for a student (optional)"
            value={r.description}
            onChange={(e) => change(i, "description")(e, e.target.value)}
          />
          <TextInput
            maxLength={120}
            renderLabel="Framework it comes from (optional)"
            value={r.framework}
            onChange={change(i, "framework")}
          />
          <TextInput
            maxLength={500}
            type="url"
            placeholder="https://"
            renderLabel="Link to where it is described (optional)"
            value={r.url}
            onChange={change(i, "url")}
          />
          <Flex gap="small" margin="x-small 0 0" wrap="wrap">
            <Button
              size="small"
              interaction={i === 0 ? "disabled" : "enabled"}
              onClick={() => setRows([...rows.slice(0, i - 1), rows[i], rows[i - 1], ...rows.slice(i + 1)])}
            >
              Move {r.name.trim() || `attribute ${i + 1}`} up
            </Button>
            <Button size="small" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
              Remove {r.name.trim() || `attribute ${i + 1}`}
            </Button>
          </Flex>
        </View>
      ))}
      <Button
        interaction={rows.length >= MAX ? "disabled" : "enabled"}
        onClick={() => setRows([...rows, { key: null, name: "", description: "", framework: "", url: "" }])}
      >
        Add an attribute
      </Button>
      {save.isError && <ErrorAlert error={save.error} />}
      {save.isSuccess && (
        <Alert variant="success" margin="small 0">
          Saved.
        </Alert>
      )}
      <View as="div" margin="small 0">
        <Button color="primary" onClick={() => save.mutate()} interaction={save.isPending ? "disabled" : "enabled"}>
          Save graduate attributes
        </Button>
      </View>
    </View>
  );
}
