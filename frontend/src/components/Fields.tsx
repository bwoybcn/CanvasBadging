// SPDX-License-Identifier: AGPL-3.0-or-later
/** Form fields that stop a mistake while it is being typed, instead of refusing the form later. */
import { Button, Flex, Text, TextArea, TextInput, View } from "@instructure/ui";
import { useId, useState, type ComponentProps } from "react";

type TextAreaProps = ComponentProps<typeof TextArea>;

/** How close to the limit the count starts to show on a long field. */
const NEARLY = 0.9;

/** The count under a limited text box, or nothing while there is plenty of room. */
export function countText(length: number, max: number): string | null {
  if (length >= max) return `${length} of ${max} characters: that is the most this can hold.`;
  if (max <= 300 || length >= max * NEARLY) return `${length} of ${max} characters.`;
  return null;
}

/**
 * A text box that cannot go over the length the server accepts. It shows a running count on
 * short fields, and near the limit on long ones, so nobody finds out by having a form refused.
 */
export function LimitedTextArea({ maxLength, value, messages, ...rest }: TextAreaProps & { maxLength: number }) {
  const count = countText(String(value ?? "").length, maxLength);
  return (
    <TextArea
      {...rest}
      value={value}
      maxLength={maxLength}
      messages={[...(messages ?? []), ...(count ? [{ type: "hint" as const, text: count }] : [])]}
    />
  );
}

const HEX = /^#[0-9a-f]{6}$/;

/**
 * Reads what someone typed as a colour code: "#1F4E79" and "1f4e79" both work. The short form
 * ("#abc") counts only once typing has finished, because every long code passes through it.
 */
export function readColour(typed: string, finished = true): string | null {
  const t = typed.trim().toLowerCase().replace(/^#?/, "#");
  if (HEX.test(t)) return t;
  if (finished && /^#[0-9a-f]{3}$/.test(t)) return `#${t[1]}${t[1]}${t[2]}${t[2]}${t[3]}${t[3]}`;
  return null;
}

interface ColourFieldProps {
  label: string;
  /** A colour as `#rrggbb`, or "" when none is set (only with `optional`). */
  value: string;
  onChange: (value: string) => void;
  /** Lets the colour be left unset, with a button to clear it. */
  optional?: boolean;
}

/**
 * Picks a colour by eye. The swatch opens the device's own colour chooser, so nobody has to
 * know what a hex code is; the code box beside it is for people who were given a brand colour
 * as a code and want to paste it. Whatever happens, the value handed back is a valid colour.
 */
export function ColourField({ label, value, onChange, optional = false }: ColourFieldProps) {
  const id = useId();
  // What is in the code box while it is being typed (it may not be a colour yet).
  const [typed, setTyped] = useState<string | null>(null);
  const valid = readColour(value);
  const bad = typed !== null && typed.trim() !== "" && readColour(typed) === null;
  const finish = () => {
    const colour = typed === null ? null : readColour(typed);
    if (colour && colour !== valid) onChange(colour);
    setTyped(null);
  };
  return (
    <View as="div" display="block" margin="small 0">
      <label htmlFor={id}>
        <Text weight="bold">{label}</Text>
      </label>
      <Flex gap="small" alignItems="end" wrap="wrap" margin="xx-small 0 0">
        <input
          id={id}
          type="color"
          className="oc-colour"
          value={valid ?? "#ffffff"}
          aria-describedby={`${id}-state`}
          onChange={(e) => {
            setTyped(null);
            onChange(e.target.value.toLowerCase());
          }}
        />
        <TextInput
          renderLabel={`${label}: colour code (optional)`}
          width="13rem"
          maxLength={7}
          value={typed ?? valid ?? ""}
          placeholder="#1f4e79"
          messages={bad ? [{ type: "newError", text: "Use a code such as #1f4e79, or choose from the swatch." }] : []}
          onChange={(_e, v) => {
            setTyped(v);
            const colour = readColour(v, false);
            if (colour) onChange(colour);
            else if (optional && !v.trim()) onChange("");
          }}
          onBlur={finish}
        />
        {optional && valid && (
          <Button
            onClick={() => {
              setTyped(null);
              onChange("");
            }}
          >
            {`Clear ${label.toLowerCase()}`}
          </Button>
        )}
      </Flex>
      <Text as="p" size="small" id={`${id}-state`}>
        {valid
          ? `Chosen: ${valid}. Select the swatch to pick another colour.`
          : "No colour chosen. Select the swatch to pick one."}
      </Text>
    </View>
  );
}
