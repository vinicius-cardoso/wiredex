import { useTranslation } from "react-i18next";
import { shortCommit, webBuild } from "./build-info";
import { useApiVersion } from "./use-api-version";

export function VersionBadge() {
  const { t } = useTranslation();
  const api = useApiVersion();
  const outdated = api.data !== undefined && api.data.version !== webBuild.version;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted">
      <span title={webBuild.commit}>
        Wiredex v{webBuild.version} · {shortCommit(webBuild.commit)}
      </span>

      {api.isError && (
        <span className="flex items-center gap-1.5 text-crit">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-crit" />
          {t("version.apiUnreachable")}
        </span>
      )}

      {api.data && !outdated && (
        <span title={api.data.commit}>{t("version.api", { version: `v${api.data.version}` })}</span>
      )}

      {api.data && outdated && (
        <span role="status" className="flex items-center gap-2 text-warn">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-warn" />
          {t("version.updateAvailable")}
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded border border-warn px-1.5 font-sans font-semibold"
          >
            {t("version.reload")}
          </button>
        </span>
      )}
    </div>
  );
}
