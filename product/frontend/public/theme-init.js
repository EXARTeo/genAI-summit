// Runs before React: apply the stored theme ("light" | "dark" | "system") with no flash.
// Keep the storage key in sync with src/shared/stores/theme.ts (THEME_STORAGE_KEY).
(function () {
  try {
    var pref = localStorage.getItem('aac.theme') || 'system';
    var dark =
      pref === 'dark' || (pref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {
    /* storage blocked: tokens.css falls back to prefers-color-scheme */
  }
})();
