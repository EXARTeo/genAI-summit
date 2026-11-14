/** Download of a code block from an answer: the file name for its fence language. */

const EXTENSIONS: Record<string, string> = {
  bash: 'sh',
  c: 'c',
  cpp: 'cpp',
  cs: 'cs',
  csharp: 'cs',
  css: 'css',
  csv: 'csv',
  diff: 'diff',
  go: 'go',
  html: 'html',
  java: 'java',
  javascript: 'js',
  js: 'js',
  json: 'json',
  jsx: 'jsx',
  kotlin: 'kt',
  markdown: 'md',
  md: 'md',
  php: 'php',
  powershell: 'ps1',
  ps1: 'ps1',
  py: 'py',
  python: 'py',
  r: 'r',
  ruby: 'rb',
  rust: 'rs',
  sh: 'sh',
  shell: 'sh',
  sql: 'sql',
  swift: 'swift',
  toml: 'toml',
  ts: 'ts',
  tsx: 'tsx',
  typescript: 'ts',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml',
  zsh: 'sh',
};

/** `snippet.py` for `python`, `Dockerfile` for `dockerfile`, `snippet.txt` when unknown. */
export function codeFileName(language: string | null | undefined): string {
  const lang = (language ?? '').trim().toLowerCase();
  if (lang === 'dockerfile') return 'Dockerfile';
  return `snippet.${EXTENSIONS[lang] ?? 'txt'}`;
}
