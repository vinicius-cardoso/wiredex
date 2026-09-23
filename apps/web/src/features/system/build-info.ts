export const webBuild = {
  version: __APP_VERSION__,
  commit: __APP_COMMIT__,
} as const;

export function shortCommit(commit: string): string {
  return /^[0-9a-f]{7,40}$/.test(commit) ? commit.slice(0, 7) : commit;
}
