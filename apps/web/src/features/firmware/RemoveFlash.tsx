import { type RefObject, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FirmwareRefusal } from "./firmware";
import { useRemoveFlash } from "./flashes";
import { refusalKey } from "./labels";

const action = "rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-surface-2";

type Props = {
  flashId: string;
  /** The button's accessible name, naming the entry so each reads apart from the others. */
  label: string;
  /** Called once the entry is gone, for a list that doesn't refetch to drop it. */
  onRemoved?: () => void;
};

/**
 * *Remove* for one entry of a flash log, which asks first where it stands (requirement 8.5):
 * on a unit's log and under a refused delete alike. Focus moves to *Keep it* when it asks, and
 * back to *Remove* when kept.
 */
export function RemoveFlash({ flashId, label, onRemoved }: Props) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);
  const removeRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const [focusOn, setFocusOn] = useState<"remove" | "keep" | null>(null);

  useEffect(() => {
    if (!focusOn) return;
    ({ remove: removeRef, keep: keepRef })[focusOn].current?.focus();
    setFocusOn(null);
  }, [focusOn]);

  if (asking) {
    return (
      <RemoveQuestion
        flashId={flashId}
        keepRef={keepRef}
        onKeep={() => {
          setAsking(false);
          setFocusOn("remove");
        }}
        onRemoved={onRemoved}
      />
    );
  }

  return (
    <button
      ref={removeRef}
      type="button"
      aria-label={label}
      onClick={() => {
        setAsking(true);
        setFocusOn("keep");
      }}
      className={`${action} border-crit text-crit`}
    >
      {t("firmware.flash.remove")}
    </button>
  );
}

type QuestionProps = {
  flashId: string;
  keepRef: RefObject<HTMLButtonElement | null>;
  onKeep: () => void;
  onRemoved: (() => void) | undefined;
};

/** The question, holding the removal, so keeping the entry forgets a removal that failed. */
function RemoveQuestion({ flashId, keepRef, onKeep, onRemoved }: QuestionProps) {
  const { t } = useTranslation();
  const remove = useRemoveFlash();
  const refusal = remove.error instanceof FirmwareRefusal ? remove.error : null;
  const key = refusalKey(refusal?.code ?? null);

  return (
    <div className="grid min-w-48 justify-items-start gap-1">
      <p>{t("firmware.flash.removeQuestion")}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate(flashId, { onSuccess: () => onRemoved?.() })}
          className={`${action} border-crit text-crit`}
        >
          {t("firmware.flash.removeConfirm")}
        </button>
        <button ref={keepRef} type="button" onClick={onKeep} className={action}>
          {t("firmware.flash.keep")}
        </button>
      </div>
      {remove.isError && (
        <p role="alert" className="text-crit">
          {key ? t(key, { item: refusal?.item ?? "" }) : t("firmware.flash.removeError")}
        </p>
      )}
    </div>
  );
}
