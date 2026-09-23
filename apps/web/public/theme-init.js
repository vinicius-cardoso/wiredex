// Resolves the theme before first paint so the page never flashes the wrong one.
// Loaded as a blocking script from index.html (a file, not inline, so the
// Content-Security-Policy can stay script-src 'self'). Mirrors src/shared/theme/theme.ts.
(() => {
  let saved = null;
  try {
    saved = localStorage.getItem("wiredex.theme");
  } catch {}
  const dark =
    saved === "dark" || (saved !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  const theme = dark ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
