/**
 * The trash's one cache. Its own file, importing nothing, so the four modules' delete hooks can
 * refresh it without importing the trash page's hooks, which import theirs.
 */
export const trashKeys = {
  all: ["trash"] as const,
};
