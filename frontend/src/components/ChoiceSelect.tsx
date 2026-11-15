// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A drop-down list that only ever shows what has really been chosen.
 *
 * InstUI's SimpleSelect shows its first option when it is given no value, and keeps showing a
 * blank box when its value arrives before its options have loaded. Either way the box can say
 * something different from the form, so a lecturer sees "Participation" and is then told to
 * choose a category. This wrapper keeps the select controlled at all times: no choice shows the
 * placeholder, and a value set before its list loaded appears once the list arrives.
 */
import { SimpleSelect } from "@instructure/ui";
import { useId, type ComponentProps } from "react";

/** Stands for "nothing chosen yet"; never a real option value. */
const NONE = "\u0000none";

export type Choice = { value: string; label: string };

type SimpleSelectProps = ComponentProps<typeof SimpleSelect>;

export type ChoiceSelectProps = {
  label: string;
  value: string | undefined;
  options: Choice[];
  onChange: (value: string) => void;
  placeholder?: string;
  interaction?: SimpleSelectProps["interaction"];
  messages?: SimpleSelectProps["messages"];
  width?: SimpleSelectProps["width"];
};

export function ChoiceSelect({ label, value, options, onChange, placeholder = "Choose one", ...rest }: ChoiceSelectProps) {
  const id = useId();
  // Until the list holds the value, say nothing is chosen. When the list loads, this changes from
  // NONE to the value, and SimpleSelect looks the option up again instead of staying blank.
  const chosen = options.some((o) => o.value === value) ? (value as string) : NONE;
  return (
    <SimpleSelect
      {...rest}
      renderLabel={label}
      value={chosen}
      placeholder={placeholder}
      onChange={(_e, { value: picked }) => {
        if (picked !== undefined && picked !== NONE) onChange(String(picked));
      }}
    >
      {options.map((o) => (
        <SimpleSelect.Option key={o.value} id={`${id}-${o.value}`} value={o.value}>
          {o.label}
        </SimpleSelect.Option>
      ))}
    </SimpleSelect>
  );
}
