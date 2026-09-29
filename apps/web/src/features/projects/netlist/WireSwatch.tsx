import type { WireColor } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { colorKey, SWATCH } from "./wireColors";

/** A wire colour as a swatch beside its name, never the swatch alone (requirement 10.5). */
export function WireSwatch({ color }: { color: WireColor | null }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      {color && (
        <span
          aria-hidden="true"
          className={`inline-block size-3 rounded-full border ${SWATCH[color]}`}
        />
      )}
      <span className={color ? undefined : "text-muted"}>{t(colorKey(color))}</span>
    </span>
  );
}
