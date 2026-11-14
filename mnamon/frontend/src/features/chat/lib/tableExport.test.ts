import { describe, expect, it } from 'vitest';
import { codeFileName } from './codeExport';
import { formatClock, formatCompactTokens, formatDuration, runSeconds } from './messageFormat';
import { rowsToCsv, rowsToHtml, rowsToMarkdown, rowsToTsv, tableFileName, tableRows } from './tableExport';

const ROWS = [
  ['Group', 'Rate'],
  ['female', '0.71'],
  ['male, "all"', '0.86'],
];

describe('tableExport', () => {
  it('reads the rendered rows, header included, whitespace collapsed', () => {
    const host = document.createElement('div');
    host.innerHTML =
      '<table><thead><tr><th> Group </th><th>Rate</th></tr></thead><tbody><tr><td><strong>female</strong>\n</td><td>0.71</td></tr></tbody></table>';
    expect(tableRows(host.querySelector('table')!)).toEqual([
      ['Group', 'Rate'],
      ['female', '0.71'],
    ]);
  });

  it('writes CSV with a BOM, CRLF and quoting only where needed', () => {
    const csv = rowsToCsv(ROWS);
    expect(csv.charCodeAt(0)).toBe(0xfeff);
    expect(csv.slice(1)).toBe('Group,Rate\r\nfemale,0.71\r\n"male, ""all""",0.86\r\n');
  });

  it('writes TSV, HTML and Markdown', () => {
    expect(rowsToTsv([['a\tb', 'c']])).toBe('a b\tc');
    expect(rowsToHtml([['<x>'], ['&']])).toBe(
      '<table><thead><tr><th>&lt;x&gt;</th></tr></thead><tbody><tr><td>&amp;</td></tr></tbody></table>',
    );
    expect(rowsToMarkdown([['a', 'b'], ['1|2']])).toBe('| a | b |\n| --- | --- |\n| 1\\|2 |  |');
    expect(rowsToMarkdown([])).toBe('');
  });

  it('names the file by local time', () => {
    expect(tableFileName(new Date(2026, 10, 15, 9, 5))).toBe('table-20261115-0905.csv');
    expect(tableFileName(new Date(2026, 0, 2, 13, 30), 'md')).toBe('table-20260102-1330.md');
  });
});

describe('codeFileName', () => {
  it('maps fence languages to file names', () => {
    expect(codeFileName('python')).toBe('snippet.py');
    expect(codeFileName('TypeScript')).toBe('snippet.ts');
    expect(codeFileName('dockerfile')).toBe('Dockerfile');
    expect(codeFileName('text')).toBe('snippet.txt');
    expect(codeFileName(undefined)).toBe('snippet.txt');
  });
});

describe('messageFormat', () => {
  it('formats compact token counts', () => {
    expect(formatCompactTokens(950)).toBe('950');
    expect(formatCompactTokens(4200)).toBe('4.2k');
    expect(formatCompactTokens(4000)).toBe('4k');
    expect(formatCompactTokens(12_400)).toBe('12k');
    expect(formatCompactTokens(1_250_000)).toBe('1.3M');
    expect(formatCompactTokens(Number.NaN)).toBe('0');
  });

  it('computes run seconds and durations', () => {
    expect(runSeconds('2026-11-15T10:00:00Z', '2026-11-15T10:00:42Z')).toBe(42);
    expect(runSeconds('2026-11-15T10:00:00Z', null)).toBeNull();
    expect(runSeconds('2026-11-15T10:00:00Z', '2026-11-15T10:00:00Z')).toBeNull();
    expect(formatDuration(42)).toBe('42 s');
    expect(formatDuration(185)).toBe('3 min 5 s');
    expect(formatDuration(120)).toBe('2 min');
  });

  it('formats a clock time, empty for bad input', () => {
    expect(formatClock('2026-11-15T10:05:00Z')).toMatch(/\d{1,2}:\d{2}/);
    expect(formatClock('nope')).toBe('');
    expect(formatClock(null)).toBe('');
  });
});
