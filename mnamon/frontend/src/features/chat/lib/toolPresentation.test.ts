// How a tool step presents itself in the chain of thought.
import { describe, expect, it } from 'vitest';
import {
  isQuietTool,
  provisionLabel,
  toolFailureLine,
  toolImages,
  toolSummary,
  basename,
  formatSubagentDuration,
  formatThinkingDuration,
  humaniseName,
  parseCommandOutput,
  parseToolArgs,
  subagentName,
  toolDurationLabel,
  toolMeta,
  toolTitle,
  toolTitleHint,
} from './toolPresentation';

describe('toolTitle', () => {
  it('titles known tools from their arguments', () => {
    expect(toolTitle('read_system_file', { path: 'data/selection_rates.csv' })).toBe(
      'Read selection_rates.csv',
    );
    expect(toolTitle('write_finding_note', { path: 'findings/F-001-note.md' })).toBe('Write F-001-note.md');
    expect(toolTitle('search_regulation', { query: 'Art. 10 bias' })).toBe(
      'Search the regulation for "Art. 10 bias"',
    );
    expect(toolTitle('ls', { path: '/systems/' })).toBe('List systems');
    expect(toolTitle('execute', { command: 'pytest -q' })).toBe('Run pytest -q');
  });

  it('keeps the raw name for unknown tools or missing arguments', () => {
    expect(toolTitle('web_search', { query: 'x' })).toBe('web_search');
    expect(toolTitle('read_file', null)).toBe('read_file');
  });

  it('hints the full path or command', () => {
    expect(toolTitleHint('read_file', { file_path: '/a/b/c.txt' })).toBe('/a/b/c.txt');
    expect(toolTitleHint('execute', { command: 'ls -la' })).toBe('ls -la');
    expect(toolTitleHint('web_search', { query: 'x' })).toBeUndefined();
  });
});

describe('parsing', () => {
  it('parses args, envelopes and streaming text', () => {
    expect(parseToolArgs('')).toBeNull();
    expect(parseToolArgs('{"a": 1}')).toEqual({ a: 1 });
    expect(parseToolArgs('{"name": "x", "args": {"a": 1}}')).toEqual({ a: 1 });
    expect(parseToolArgs('{"a": ')).toBe('{"a":');
  });

  it('splits the exit code off a command output', () => {
    expect(parseCommandOutput('0.83\n[Command succeeded with exit code 0]')).toEqual({
      output: '0.83',
      exitCode: 0,
    });
    expect(parseCommandOutput('plain')).toEqual({ output: 'plain' });
    expect(parseCommandOutput(undefined)).toBeNull();
  });

  it('names things', () => {
    expect(basename('/systems/SYS-001/data/rates.csv')).toBe('rates.csv');
    expect(humaniseName('fetch_weather')).toBe('Fetch weather');
    expect(subagentName('research_agent')).toBe('research');
    expect(subagentName('evidence-checker')).toBe('evidence-checker');
  });
});

describe('meta and durations', () => {
  it('notes exit codes, list sizes and sources', () => {
    expect(toolMeta('execute', 'x\n[Command failed with exit code 2]')).toBe('exit 2');
    expect(toolMeta('ls', "['/a', '/b/']")).toBe('2 items');
    expect(toolMeta('search_regulation', 'text', 2)).toBe('2 sources');
    expect(toolMeta('web_search', undefined)).toBeUndefined();
  });

  it('formats durations like magenticx', () => {
    expect(toolDurationLabel(0, 850)).toBe('850ms');
    expect(toolDurationLabel(0, 2900)).toBe('2.9s');
    expect(toolDurationLabel(0, 12_400)).toBe('12s');
    expect(toolDurationLabel(undefined, 10)).toBeUndefined();
    expect(formatThinkingDuration(0, 7_200)).toBe('7s');
    expect(formatThinkingDuration(0, 64_000)).toBe('1m 4s');
    expect(formatSubagentDuration(0, 300)).toBe('<1s');
    expect(formatSubagentDuration(0, 185_000)).toBe('3m 05s');
  });
});

describe('quiet tools', () => {
  it('names the workspace tools', () => {
    expect(toolTitle('list_systems', {})).toBe('List systems');
    expect(toolTitle('list_system_files', { system_id: 'SYS-001' })).toBe("List SYS-001's files");
    expect(toolTitle('lookup_provision', { provision_id: 'AIA.10.2' })).toBe('Look up Art. 10(2)');
    expect(provisionLabel('AIA.1.2.f')).toBe('Art. 1(2)(f)');
  });

  it('marks read, list and search tools quiet, never write or run tools', () => {
    for (const name of ['list_systems', 'read_system_file', 'grep', 'search_regulation', 'view_image'])
      expect(isQuietTool(name)).toBe(true);
    for (const name of ['write_file', 'execute', 'propose_system_note', 'start_audit', 'task'])
      expect(isQuietTool(name)).toBe(false);
  });

  it('summarises what came back', () => {
    const systems = JSON.stringify([
      { id: 'SYS-001', name: 'CV Screener' },
      { id: 'SYS-002', name: 'Credit Scorer' },
    ]);
    expect(toolSummary('list_systems', systems)).toBe(
      '2 systems: SYS-001 CV Screener, SYS-002 Credit Scorer',
    );
    expect(toolSummary('list_system_files', '/systems/SYS-001/\na.md (v1)\nb.yaml (v2)')).toBe('2 files');
    expect(toolSummary('grep', 'No matches found')).toBe('No matches');
    const search = JSON.stringify({
      items: [{ id: 'AIA.10', title: 'Data and data governance' }, { id: 'AIA.10.2' }],
    });
    expect(toolSummary('search_regulation', search)).toBe(
      '2 provisions: Art. 10 Data and data governance, Art. 10(2)',
    );
    expect(toolSummary('read_system_file', JSON.stringify('line 1\nline 2'))).toBe('2 lines read');
    expect(toolSummary('list_systems', 'Could not list systems: timeout.')).toBe(
      'Could not list systems: timeout.',
    );
  });

  it('pulls image thumbnails out of a result', () => {
    const result = JSON.stringify([{ type: 'image', preview_base64: 'AAAA', mime_type: 'image/jpeg' }]);
    expect(toolImages(result)).toEqual([{ src: 'data:image/jpeg;base64,AAAA', alt: 'Image' }]);
    expect(toolImages('plain text')).toEqual([]);
  });
});

describe('quiet tool failures', () => {
  it('hides Python exceptions behind a plain line', () => {
    expect(
      toolFailureLine("Tool 'lookup_provision' failed: AttributeError: 'str' object has no attribute 'get'"),
    ).toBe("Couldn't complete this step");
    expect(toolFailureLine('Could not read AIA.10.2: not found.')).toBe(
      'Could not read AIA.10.2: not found.',
    );
  });
});
