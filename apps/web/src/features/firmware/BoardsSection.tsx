import { Link } from "@tanstack/react-router";
import type { Board, FirmwareDetails } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { Block, type BlockSpan, StackedTable } from "../../shared/ui/block";
import { revisionName } from "../projects/projects";
import { useBoards, useTimeFormat } from "./flashes";

const cell = "px-2 py-1.5";

/**
 * The boards running a firmware, on its page (requirement 8.6): the units whose newest flash
 * is one of its versions, by code, each linking to its unit's page, with that version, when it
 * was flashed, the revision holding the unit now, and a newer release in words and an icon. A
 * retired or deleted unit is already left out (4.2). The table scrolls in its own box (8.11)
 * and turns into a card per board where the block is narrow.
 */
export function BoardsSection({
  firmware,
  span,
}: {
  firmware: FirmwareDetails;
  span?: BlockSpan | undefined;
}) {
  const { t } = useTranslation();
  const boards = useBoards(firmware.id);

  return (
    <Block title={t("firmware.boards.title")} span={span}>
      {/* Data first: a refetch that fails keeps showing what was loaded. */}
      {boards.data ? (
        boards.data.length === 0 ? (
          <p className="text-sm text-muted">{t("firmware.boards.none")}</p>
        ) : (
          <BoardTable firmware={firmware} boards={boards.data} />
        )
      ) : boards.isError ? (
        <p role="alert" className="text-sm text-crit">
          {t("firmware.boards.error")}
        </p>
      ) : (
        <p className="text-sm text-muted">{t("firmware.boards.loading")}</p>
      )}
    </Block>
  );
}

function BoardTable({ firmware, boards }: { firmware: FirmwareDetails; boards: Board[] }) {
  const { t } = useTranslation();
  const format = useTimeFormat();

  return (
    <StackedTable below="xs">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">
          {t("firmware.boards.caption", { name: firmware.name })}
        </caption>
        <thead>
          <tr className="border-b border-border text-muted">
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.boards.columns.board")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.boards.columns.version")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.boards.columns.flashed")}
            </th>
            <th scope="col" className={`${cell} font-medium`}>
              {t("firmware.boards.columns.revision")}
            </th>
          </tr>
        </thead>
        <tbody>
          {boards.map((board) => {
            const { flash, newer_release: newer, revision } = board;
            return (
              <tr key={board.unit.id} className="border-b border-border align-top">
                {/* A code is short and read as one word: it never breaks at its hyphens. */}
                <th scope="row" className={`${cell} font-normal whitespace-nowrap`}>
                  <Link
                    to="/units/$unitId"
                    params={{ unitId: board.unit.id }}
                    className="font-mono text-primary hover:underline"
                  >
                    {board.unit.code}
                  </Link>
                </th>
                <td data-label={t("firmware.boards.columns.version")} className={cell}>
                  <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <Link
                      to="/firmware/$firmwareId/versions/$versionId"
                      params={{ firmwareId: firmware.id, versionId: flash.version.id }}
                      className="font-mono text-primary hover:underline"
                    >
                      {flash.version.version}
                    </Link>
                    {/* A mismatch is --warn (decision 10), and says so in words beside its icon. */}
                    {newer && (
                      <Link
                        to="/firmware/$firmwareId/versions/$versionId"
                        params={{ firmwareId: firmware.id, versionId: newer.id }}
                        className="font-semibold whitespace-nowrap text-warn hover:underline"
                      >
                        <span aria-hidden="true">⚠ </span>
                        {t("firmware.flash.newer", { version: newer.version })}
                      </Link>
                    )}
                  </span>
                </td>
                <td
                  data-label={t("firmware.boards.columns.flashed")}
                  className={`${cell} whitespace-nowrap`}
                >
                  <time dateTime={flash.flashed_at}>{format(flash.flashed_at)}</time>
                </td>
                <td
                  data-label={t("firmware.boards.columns.revision")}
                  className={`${cell} min-w-32 break-words`}
                >
                  {revision ? (
                    <Link
                      to="/projects/$projectId/revisions/$revisionId"
                      params={{
                        projectId: revision.project_id,
                        revisionId: revision.revision_id,
                      }}
                      className="text-primary hover:underline"
                    >
                      {t("firmware.page.runsOnEntry", {
                        project: revision.project_name,
                        revision: revisionName(t, revision),
                      })}
                    </Link>
                  ) : (
                    <span className="text-muted">{t("firmware.boards.noRevision")}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </StackedTable>
  );
}
