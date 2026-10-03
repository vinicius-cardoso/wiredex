import { getRouteApi, Link } from "@tanstack/react-router";
import type { RevisionRef, UnitResponse } from "@wiredex/api-client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FilterBar,
  FilterField,
  filterButton,
  filterControl,
  ListCount,
  listCell,
  listHead,
  listHeadCell,
  listPage,
  listRow,
  listTable,
  PageHeader,
  TableFrame,
} from "../../shared/ui/list";
import { useRevisionRefs } from "../projects/build/lifecycle";
import { RevisionRefLink } from "../projects/build/RevisionLink";
import { isHeld } from "./inventory";
import {
  BOARDS_LIMIT,
  type BoardFilters,
  type BoardSearch,
  UNIT_STATUSES,
  useBoards,
} from "./units";

/** How long typing pauses before the address, and so the list, changes. */
const DEBOUNCE_MS = 300;

/** The whole list, which the part filter's choices are read off. */
const EVERY_BOARD: BoardFilters = { q: "", status: null, partId: null };

const route = getRouteApi("/authenticated/units");

/**
 * Every tracked board of the bench, the last received first, at most 200: its code, part,
 * serial, MAC, status, where it sits and the build holding it. One bar narrows it by a code,
 * serial or MAC fragment, a status and a part, all kept in the address (`q`, `status`, `part`),
 * so a narrowed list can be bookmarked and walked with Back. The box edits a draft that feels
 * instant, written to the address once typing pauses; a select writes at once.
 */
export function BoardsPage() {
  const { t } = useTranslation();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const searchId = useId();
  const statusId = useId();
  const partId = useId();

  const q = search.q ?? "";
  const [draft, setDraft] = useState(q);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Back, Forward or a shared link change the address without touching the draft; adopt the
  // address's text then, in render rather than an effect, so there is no extra paint.
  const lastQ = useRef(q);
  if (lastQ.current !== q) {
    lastQ.current = q;
    setDraft(q);
  }

  useEffect(() => () => clearTimeout(timer.current), []);

  function commit(next: BoardSearch) {
    void navigate({ search: next, replace: true });
  }

  /** The address for the filters, the one being changed taken from `change`. */
  function searchFor(change: { q?: string; status?: string; part?: string }): BoardSearch {
    const next: BoardSearch = {};
    const text = (change.q ?? draft).trim();
    if (text) next.q = text;
    const status = UNIT_STATUSES.find((known) => known === (change.status ?? search.status));
    if (status) next.status = status;
    const part = change.part ?? search.part;
    if (part) next.part = part;
    return next;
  }

  function type(text: string) {
    setDraft(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit(searchFor({ q: text })), DEBOUNCE_MS);
  }

  function choose(change: { status: string } | { part: string }) {
    clearTimeout(timer.current);
    commit(searchFor(change));
  }

  function clear() {
    clearTimeout(timer.current);
    setDraft("");
    commit({});
  }

  const filters: BoardFilters = { q, status: search.status ?? null, partId: search.part ?? null };
  const boards = useBoards(filters);
  // The part filter offers the parts the bench's boards are of, read off the whole list; with
  // nothing narrowing it, that is the same request as the list's.
  const every = useBoards(EVERY_BOARD);
  const parts = partChoices(
    every.data ?? [],
    boards.data ?? [],
    search.part,
    t("inventory.boards.unknownPart"),
  );
  const narrowed = q !== "" || search.status !== undefined || search.part !== undefined;
  const rows = boards.data ?? [];

  return (
    <section className={listPage}>
      <PageHeader title={t("inventory.boards.title")} intro={t("inventory.boards.intro")} />
      <FilterBar>
        <FilterField label={t("inventory.boards.search")} htmlFor={searchId} grow>
          <input
            id={searchId}
            type="search"
            value={draft}
            placeholder={t("inventory.boards.searchPlaceholder")}
            onChange={(event) => type(event.target.value)}
            className={`${filterControl} font-mono`}
          />
        </FilterField>
        <FilterField label={t("inventory.boards.status")} htmlFor={statusId}>
          <select
            id={statusId}
            value={search.status ?? ""}
            onChange={(event) => choose({ status: event.target.value })}
            className={`${filterControl} sm:w-44`}
          >
            <option value="">{t("inventory.boards.anyStatus")}</option>
            {UNIT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {t(`inventory.units.status.${status}`)}
              </option>
            ))}
          </select>
        </FilterField>
        <FilterField label={t("inventory.boards.part")} htmlFor={partId}>
          <select
            id={partId}
            value={search.part ?? ""}
            onChange={(event) => choose({ part: event.target.value })}
            className={`${filterControl} sm:w-60`}
          >
            <option value="">{t("inventory.boards.anyPart")}</option>
            {parts.map((part) => (
              <option key={part.id} value={part.id}>
                {part.name}
              </option>
            ))}
          </select>
        </FilterField>
        {narrowed && (
          <button type="button" onClick={clear} className={filterButton}>
            {t("inventory.boards.clear")}
          </button>
        )}
      </FilterBar>

      {boards.isPending && <p className="text-muted">{t("inventory.boards.loading")}</p>}
      {boards.isError && (
        <p role="alert" className="text-crit">
          {t("inventory.boards.error")}
        </p>
      )}
      {boards.data && rows.length === 0 && (
        <div className="grid max-w-prose justify-items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
          <p className="text-muted">
            {narrowed ? t("inventory.boards.noMatches") : t("inventory.boards.empty")}
          </p>
        </div>
      )}
      {rows.length > 0 && <BoardsTable boards={rows} />}
      {rows.length >= BOARDS_LIMIT && (
        <ListCount>{t("inventory.boards.capped", { count: BOARDS_LIMIT })}</ListCount>
      )}
    </section>
  );
}

type PartChoice = { id: string; name: string };

/**
 * The parts the boards are of, by name, each once; the one the address names stays offered
 * even when no board of the whole list shows it, so the filter can always be switched off.
 */
function partChoices(
  every: UnitResponse[],
  shown: UnitResponse[],
  chosen: string | undefined,
  unknown: string,
): PartChoice[] {
  const names = new Map<string, string>();
  for (const board of [...every, ...shown]) {
    if (!names.has(board.part_id)) names.set(board.part_id, board.part_name ?? unknown);
  }
  if (chosen && !names.has(chosen)) names.set(chosen, unknown);
  return [...names]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function BoardsTable({ boards }: { boards: UnitResponse[] }) {
  const { t } = useTranslation();
  const blank = t("inventory.units.blank");

  // The builds holding a board, named in one request for the whole list. Memoised on the
  // joined ids, so a new array with the same ids doesn't change the query key.
  const held = [
    ...new Set(
      boards
        .filter((board) => isHeld(board.status) && board.revision_id !== null)
        .map((board) => board.revision_id as string),
    ),
  ];
  // biome-ignore lint/correctness/useExhaustiveDependencies: the join is the identity we key on.
  const heldIds = useMemo(() => held, [held.join(",")]);
  const refs = useRevisionRefs(heldIds);

  return (
    // A long name or MAC scrolls the table inside its own box, never the page.
    <TableFrame>
      <table className={listTable}>
        <caption className="sr-only">{t("inventory.boards.title")}</caption>
        <thead className={listHead}>
          <tr>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.code")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.part")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.serial")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.mac")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.status")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.location")}
            </th>
            <th scope="col" className={listHeadCell}>
              {t("inventory.boards.columns.revision")}
            </th>
          </tr>
        </thead>
        <tbody>
          {boards.map((board) => (
            <tr key={board.id} className={listRow}>
              <th scope="row" className={`${listCell} font-normal`}>
                <Link
                  to="/units/$unitId"
                  params={{ unitId: board.id }}
                  className="font-mono text-primary hover:underline"
                >
                  {board.code}
                </Link>
              </th>
              <td className={listCell}>
                <Link
                  to="/parts/$partId"
                  params={{ partId: board.part_id }}
                  className={`hover:underline ${board.part_name ? "" : "text-warn"}`}
                >
                  {board.part_name ?? t("inventory.boards.unknownPart")}
                </Link>
              </td>
              <td className={listCell}>{board.serial ?? blank}</td>
              <td className={`${listCell} font-mono text-xs`}>{board.mac ?? blank}</td>
              <td className={`${listCell} whitespace-nowrap`}>
                {t(`inventory.units.status.${board.status}`)}
              </td>
              <td className={listCell}>
                {board.location ? (
                  <>
                    {board.location.name}{" "}
                    <span className="font-mono text-xs text-muted">{board.location.code}</span>
                  </>
                ) : (
                  blank
                )}
              </td>
              <td className={listCell}>
                <HeldBy board={board} refs={refs.data} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableFrame>
  );
}

/** The build a held board is reserved for or built into, while its name loads a quiet line. */
function HeldBy({
  board,
  refs,
}: {
  board: UnitResponse;
  refs: Map<string, RevisionRef> | undefined;
}) {
  const { t } = useTranslation();
  if (!isHeld(board.status) || board.revision_id === null) return null;
  if (refs === undefined) {
    return <span className="text-muted">{t("projects.holdings.loadingRevision")}</span>;
  }
  const ref = refs.get(board.revision_id);
  return ref ? <RevisionRefLink revision={ref} /> : <>{t("inventory.units.blank")}</>;
}
