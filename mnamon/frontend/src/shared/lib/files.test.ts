import { describe, expect, it } from 'vitest';
import {
  baseName,
  blobFromBase64,
  classifyFile,
  downloadName,
  fileExtension,
  fileSubtitle,
  formatFileSize,
  guessMime,
  isImageFile,
  parseCsv,
} from './files';

describe('classifyFile', () => {
  it('detects kinds by MIME type first, then extension', () => {
    expect(classifyFile({ name: 'x.bin', mime: 'application/pdf' }).kind).toBe('pdf');
    expect(classifyFile({ name: 'report.PDF' }).kind).toBe('pdf');
    expect(classifyFile({ name: 'a.png', mime: 'image/png' }).kind).toBe('image');
    expect(classifyFile({ name: 'photo.jpeg' }).kind).toBe('image');
    expect(classifyFile({ name: 'notes.md' }).kind).toBe('markdown');
    expect(classifyFile({ name: 'rows.csv' }).kind).toBe('csv');
    expect(classifyFile({ name: 'x.json' }).kind).toBe('json');
    expect(classifyFile({ name: 'a.docx' }).kind).toBe('docx');
    expect(classifyFile({ name: 'log.txt' }).kind).toBe('text');
    expect(classifyFile({ name: 'blob', mime: 'text/plain' }).kind).toBe('text');
    expect(classifyFile({ name: 'model.pkl' }).kind).toBe('unsupported');
  });

  it('labels code with its language', () => {
    expect(classifyFile({ name: 'system-card.yaml' })).toMatchObject({
      kind: 'code',
      language: 'yaml',
      label: 'YAML',
    });
    expect(classifyFile({ name: 'x', mime: 'application/yaml' })).toMatchObject({
      kind: 'code',
      language: 'yaml',
    });
    expect(classifyFile({ name: 'run.py' })).toMatchObject({ kind: 'code', language: 'python' });
  });

  it('refuses SVG, legacy Office and oversized text', () => {
    expect(classifyFile({ name: 'logo.svg', mime: 'image/svg+xml' }).previewable).toBe(false);
    expect(classifyFile({ name: 'logo.svg' }).previewable).toBe(false);
    expect(classifyFile({ name: 'old.xls' }).previewable).toBe(false);
    const big = classifyFile({ name: 'big.csv', size: 6 * 1024 * 1024 });
    expect(big.previewable).toBe(false);
    expect(big.reason).toMatch(/5 MB/);
  });

  it('isImageFile', () => {
    expect(isImageFile({ name: 'a.webp' })).toBe(true);
    expect(isImageFile({ name: 'a.pdf' })).toBe(false);
  });
});

describe('helpers', () => {
  it('fileExtension and baseName', () => {
    expect(fileExtension('a/b.tar.GZ')).toBe('gz');
    expect(fileExtension('README')).toBe('');
    expect(baseName('/systems/SYS-001/plugins/x/plugin.yaml')).toBe('plugin.yaml');
  });

  it('guessMime fills what the browser leaves empty', () => {
    expect(guessMime({ name: 'a.md', type: '' })).toBe('text/markdown');
    expect(guessMime({ name: 'a.yml' })).toBe('application/yaml');
    expect(guessMime({ name: 'a.JPG' })).toBe('image/jpeg');
    expect(guessMime({ name: 'a.bin' })).toBe('application/octet-stream');
    expect(guessMime({ name: 'a.md', type: 'Text/Plain' })).toBe('text/plain');
  });

  it('formatFileSize', () => {
    expect(formatFileSize(undefined)).toBe('');
    expect(formatFileSize(512)).toBe('512 B');
    expect(formatFileSize(2048)).toBe('2.0 KB');
    expect(formatFileSize(20 * 1024)).toBe('20 KB');
    expect(formatFileSize(3 * 1024 * 1024)).toBe('3.0 MB');
  });

  it('fileSubtitle', () => {
    expect(fileSubtitle({ name: 'a.pdf', size: 2048 })).toBe('PDF · 2.0 KB');
    expect(fileSubtitle({ name: 'a.bin', mime: 'application/zip' }, ['Generated'])).toBe(
      'Generated · application/zip',
    );
  });

  it('downloadName adds a missing extension', () => {
    expect(downloadName('image', 'image/png')).toBe('image.png');
    expect(downloadName('a.png', 'image/png')).toBe('a.png');
    expect(downloadName('', undefined)).toBe('file');
  });

  it('blobFromBase64', () => {
    const blob = blobFromBase64(btoa('hello'), 'text/plain');
    expect(blob.type).toBe('text/plain');
    expect(blob.size).toBe(5);
  });
});

describe('parseCsv', () => {
  it('handles quotes, escaped quotes, commas and line breaks in cells', () => {
    const rows = parseCsv('a,b,c\r\n1,"x, y","say ""hi"""\n2,"line\nbreak",3\n\n');
    expect(rows).toEqual([
      ['a', 'b', 'c'],
      ['1', 'x, y', 'say "hi"'],
      ['2', 'line\nbreak', '3'],
    ]);
  });

  it('stops at the limit and strips a BOM', () => {
    expect(parseCsv('\uFEFFh\n1\n2\n3', 2)).toEqual([['h'], ['1']]);
  });
});
