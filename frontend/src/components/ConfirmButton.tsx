// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A button that asks before it acts.
 *
 * For anything that cannot simply be undone with the next click (archiving a badge, deleting a
 * draft, taking away someone's role). The first press changes nothing: it shows what will
 * happen and offers the action beside a way out. Focus moves to the way out, so pressing Enter
 * twice by habit does not go through with it.
 */
import { Button, Text, View } from "@instructure/ui";
import { useEffect, useRef, useState, type ComponentProps } from "react";

interface Props {
  /** The button as it first appears, for example "Archive". */
  label: string;
  /** What will happen, in a sentence or two, shown once the button is pressed. */
  consequence: string;
  /** The button that goes through with it, for example "Archive this badge". */
  confirmLabel: string;
  /** The way out. */
  cancelLabel?: string;
  onConfirm: () => void;
  color?: ComponentProps<typeof Button>["color"];
  size?: ComponentProps<typeof Button>["size"];
  /** The colour of the button that goes through with it: red unless the action is a good thing. */
  confirmColor?: ComponentProps<typeof Button>["color"];
  /** True while the action is running: both buttons wait. */
  busy?: boolean;
}

export function ConfirmButton({
  label,
  consequence,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  color = "secondary",
  size = "medium",
  confirmColor = "danger",
  busy = false,
}: Props) {
  const [asking, setAsking] = useState(false);
  const cancel = useRef<HTMLElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (asking) cancel.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      opener.current?.focus();
    }
  }, [asking]);

  if (!asking)
    return (
      <Button color={color} size={size} elementRef={(el) => (opener.current = el as HTMLElement | null)} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  return (
    <View
      as="div"
      display="inline-block"
      role="group"
      aria-label={label}
      borderWidth="small"
      borderRadius="medium"
      padding="x-small small"
    >
      <Text as="p" role="alert">
        {consequence}
      </Text>
      <Button
        size={size}
        color={confirmColor}
        margin="0 x-small 0 0"
        interaction={busy ? "disabled" : "enabled"}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button
        size={size}
        elementRef={(el) => (cancel.current = el as HTMLElement | null)}
        onClick={() => {
          returnFocus.current = true;
          setAsking(false);
        }}
      >
        {cancelLabel}
      </Button>
    </View>
  );
}
