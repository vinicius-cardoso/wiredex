/** A repository's address without its scheme, as a link shows it: `github.com/owner/repo`. */
export function repositoryName(repository: string): string {
  return repository.replace(/^https?:\/\//, "");
}

/**
 * Where a commit opens in its repository. GitHub, GitLab, Gitea, Forgejo and Codeberg all
 * answer `/commit/<name>`; Bitbucket spells it `/commits/`.
 */
export function commitUrl(repository: string, commit: string): string {
  const pages = /^https?:\/\/bitbucket\.org\//.test(repository) ? "commits" : "commit";
  return `${repository}/${pages}/${commit}`;
}

/** The first seven digits, as `git log --oneline` shows a commit. */
export function shortCommit(commit: string): string {
  return commit.slice(0, 7);
}
