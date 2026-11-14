import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { useUiStore } from '@/shared/stores/ui';
import { MemoryChip } from './common';

describe('MemoryChip', () => {
  beforeEach(() => useUiStore.setState({ memoryEntryId: null }));

  it('opens the lesson in the global side sheet instead of navigating', async () => {
    render(<MemoryChip id="MEM-0042" />);
    await userEvent.click(screen.getByRole('button', { name: /applied MEM-0042/ }));
    expect(useUiStore.getState().memoryEntryId).toBe('MEM-0042');
  });
});
