import type { SharedDemo } from "@wiredex/api-client";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { control, dialogPrimary, StockDialog } from "../inventory/StockDialog";
import { ShareError, useShareDemo } from "./auth";

const secondary = "rounded-md border border-border-strong px-4 py-2 hover:bg-surface-2";

/**
 * Shares a demo: an email, a name and for how many days, and the guest gets an account that
 * expires and a bench of their own with the sample data, none of the inviter's. Nothing is
 * emailed: the dialog then shows the login to pass on, the password this once, with a button
 * that copies it all.
 */
export function ShareDemoDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const ids = { email: useId(), name: useId(), days: useId(), failure: useId() };
  const share = useShareDemo();
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    share.mutate({
      email: String(form.get("email") ?? "").trim(),
      name: String(form.get("name") ?? "").trim() || null,
      days: Number(form.get("days")),
    });
  }

  if (share.data) return <Shared shared={share.data} onClose={onClose} />;

  const reason = share.error instanceof ShareError ? share.error.reason : "unavailable";
  return (
    <StockDialog title={t("account.share.title")} onClose={onClose}>
      <p className="text-sm text-muted">{t("account.share.intro")}</p>
      <form onSubmit={submit} className="grid gap-3">
        <div className="grid gap-1">
          <label htmlFor={ids.email} className="text-sm font-medium">
            {t("account.share.email")}
          </label>
          <input
            ref={emailRef}
            id={ids.email}
            name="email"
            type="email"
            required
            autoComplete="off"
            aria-describedby={share.isError ? ids.failure : undefined}
            className={control}
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={ids.name} className="text-sm font-medium">
            {t("account.share.name")}
          </label>
          <input
            id={ids.name}
            name="name"
            type="text"
            maxLength={80}
            autoComplete="off"
            placeholder={t("account.share.namePlaceholder")}
            className={control}
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={ids.days} className="text-sm font-medium">
            {t("account.share.days")}
          </label>
          <input
            id={ids.days}
            name="days"
            type="number"
            required
            min={1}
            max={90}
            step={1}
            defaultValue={7}
            className={`${control} w-28`}
          />
          <p className="text-xs text-muted">{t("account.share.daysHint")}</p>
        </div>
        {share.isError && (
          <p id={ids.failure} role="alert" className="text-sm text-crit">
            {t(`account.share.error.${reason}`)}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} className={secondary}>
            {t("account.share.cancel")}
          </button>
          <button type="submit" disabled={share.isPending} className={dialogPrimary}>
            {share.isPending ? t("account.share.sharing") : t("account.share.submit")}
          </button>
        </div>
      </form>
    </StockDialog>
  );
}

/** The guest's login, to pass on. The password is on screen now and nowhere afterwards. */
function Shared({ shared, onClose }: { shared: SharedDemo; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const until = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "long",
    timeStyle: "short",
  }).format(new Date(shared.expires_at));
  const address = window.location.origin;
  const message = t("account.share.message", {
    name: shared.name,
    address,
    email: shared.email,
    password: shared.password,
    until,
  });

  async function copy() {
    try {
      await navigator.clipboard.writeText(message);
      setCopied("yes");
    } catch {
      // No clipboard outside a secure context, or it refused: the text is there to select.
      setCopied("no");
    }
  }

  return (
    <StockDialog title={t("account.share.doneTitle", { name: shared.name })} onClose={onClose}>
      <p className="text-sm">{t("account.share.doneIntro")}</p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 rounded-md bg-surface-2 p-3 text-sm">
        <dt className="text-muted">{t("account.share.address")}</dt>
        <dd className="font-mono break-all">{address}</dd>
        <dt className="text-muted">{t("account.share.email")}</dt>
        <dd className="font-mono break-all">{shared.email}</dd>
        <dt className="text-muted">{t("account.share.password")}</dt>
        <dd className="font-mono break-all">{shared.password}</dd>
        <dt className="text-muted">{t("account.share.until")}</dt>
        <dd>{until}</dd>
      </dl>
      <p className="text-sm text-warn">{t("account.share.once")}</p>
      <p role="status" className="min-h-5 text-sm text-muted">
        {copied === "yes" && t("account.share.copied")}
        {copied === "no" && t("account.share.copyFailed")}
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onClose} className={secondary}>
          {t("account.share.close")}
        </button>
        <button type="button" onClick={copy} className={dialogPrimary}>
          {t("account.share.copy")}
        </button>
      </div>
    </StockDialog>
  );
}
