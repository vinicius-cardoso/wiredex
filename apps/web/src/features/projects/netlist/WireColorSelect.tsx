import type { WireColor } from "@wiredex/api-client";
import { type Ref, useId } from "react";
import { useTranslation } from "react-i18next";
import { colorKey, SWATCH, WIRE_COLORS } from "./wireColors";

type Props = {
  label: string;
  value: WireColor | null;
  onChange: (color: WireColor | null) => void;
  ref?: Ref<HTMLSelectElement>;
};

/** A net's wire colour: a native select of the ten and none, its swatch beside it (10.5). */
export function WireColorSelect({ label, value, onChange, ref }: Props) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <span
        aria-hidden="true"
        className={`inline-block size-3 shrink-0 rounded-full border ${value ? SWATCH[value] : "border-border-strong"}`}
      />
      <select
        ref={ref}
        id={id}
        value={value ?? ""}
        onChange={(event) => onChange((event.target.value || null) as WireColor | null)}
        className="rounded-md border border-border-strong bg-surface px-2 py-1.5 text-text"
      >
        <option value="">{t(colorKey(null))}</option>
        {WIRE_COLORS.map((color) => (
          <option key={color} value={color}>
            {t(colorKey(color))}
          </option>
        ))}
      </select>
    </div>
  );
}
