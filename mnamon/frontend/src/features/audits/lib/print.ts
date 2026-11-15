// PDF export: print one element in its own window with the app's stylesheets, light theme.
// The browser's "Save as PDF" makes the file; nothing is rendered server-side.

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

/** Opens a print window for `el` (falls back to printing the page when pop-ups are blocked). */
export function printElement(el: HTMLElement, title: string): void {
  const w = window.open('', '_blank', 'noopener=no,width=1024,height=1200');
  if (!w) {
    window.print();
    return;
  }
  // Inline the app's CSS rules (same-origin sheets are readable), so nothing has to load in the new window.
  const css = [...document.styleSheets]
    .map((sheet) => {
      try {
        return [...sheet.cssRules].map((r) => r.cssText).join('\n');
      } catch {
        return sheet.href ? `@import url("${sheet.href}");` : '';
      }
    })
    .join('\n')
    .replace(/<\/style/gi, '<\\/style');
  const styles = `<style>${css}</style>`;
  w.document.open();
  w.document.write(`<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<title>${escapeHtml(title)}</title>
${styles}
<style>
  @page { size: A4; margin: 16mm 14mm; }
  html, body { background: rgb(var(--surface)); }
  body { padding: 0; margin: 0; }
  .report-print-root { max-width: 100%; padding: 0; }
  .print\\:hidden, [data-print="hide"] { display: none !important; }
  article, section, table, tr, li { break-inside: avoid; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
</style>
</head>
<body class="bg-surface text-text"><div class="report-print-root">${el.innerHTML}</div></body>
</html>`);
  w.document.close();
  // Print only once every stylesheet has loaded (or failed, or 4 s passed) and fonts are ready:
  // printing earlier gives an unstyled PDF.
  const sheets = [...w.document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].map(
    (l) =>
      new Promise<void>((resolve) => {
        if (l.sheet) return resolve();
        l.addEventListener('load', () => resolve(), { once: true });
        l.addEventListener('error', () => resolve(), { once: true });
      }),
  );
  const timeout = new Promise<void>((resolve) => setTimeout(resolve, 4000));
  void Promise.race([Promise.all(sheets), timeout])
    .then(() =>
      Promise.race([w.document.fonts?.ready, new Promise<void>((resolve) => setTimeout(resolve, 1500))]),
    )
    .then(() => {
      w.focus();
      w.print();
    });
}
