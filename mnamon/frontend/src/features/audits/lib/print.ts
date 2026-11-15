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
  const styles = [
    ...document.querySelectorAll<HTMLLinkElement | HTMLStyleElement>('link[rel="stylesheet"], style'),
  ]
    .map((n) =>
      n instanceof HTMLLinkElement ? `<link rel="stylesheet" href="${escapeHtml(n.href)}">` : n.outerHTML,
    )
    .join('\n');
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
  const go = () => {
    w.focus();
    w.print();
  };
  // Wait for the stylesheets and fonts, then print.
  if (w.document.readyState === 'complete') setTimeout(go, 300);
  else w.addEventListener('load', () => setTimeout(go, 300));
}
