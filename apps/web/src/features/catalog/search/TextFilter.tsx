import type { SchemaAttribute } from "@wiredex/api-client";
import { useId } from "react";

const control = "rounded-md border border-border-strong bg-surface px-3 py-2 text-text";

type TextFilter = { type: "text"; key: string; text: string };

type Props = {
  attribute: SchemaAttribute;
  /** The fragment the owner has typed, if any. */
  filter: TextFilter | undefined;
  /** The new fragment, or null when it is blank and the filter is dropped. */
  onChange: (filter: TextFilter | null) => void;
};

/**
 * A text box for a text attribute (requirement 6.1): a part whose value contains the
 * fragment matches. A blank box drops the filter.
 */
export function TextFilter({ attribute, filter, onChange }: Props) {
  const id = useId();
  const value = filter?.text ?? "";

  function change(next: string) {
    onChange(next.trim() === "" ? null : { type: "text", key: attribute.key, text: next });
  }

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {attribute.label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(event) => change(event.target.value)}
        className={control}
      />
    </div>
  );
}
