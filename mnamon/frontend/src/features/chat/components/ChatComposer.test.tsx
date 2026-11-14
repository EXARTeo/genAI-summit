import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import { useComposer } from '../hooks/useComposer';
import { ChatComposer } from './ChatComposer';

function setup(overrides: Partial<Parameters<typeof ChatComposer>[0]> = {}) {
  const { result } = renderHook(() => useComposer());
  const onSubmit = vi.fn();
  const onCommand = vi.fn();
  const onStop = vi.fn();
  const view = (props = overrides) => (
    <TooltipProvider>
      <ChatComposer
        composer={result.current}
        onSubmit={onSubmit}
        onStop={onStop}
        onCommand={onCommand}
        running={false}
        sending={false}
        hasConversation
        {...props}
      />
    </TooltipProvider>
  );
  const utils = render(view());
  return { result, onSubmit, onCommand, onStop, rerender: (p = overrides) => utils.rerender(view(p)) };
}

describe('ChatComposer', () => {
  it('sends on Enter, not on Shift+Enter', () => {
    const { result, onSubmit, rerender } = setup();
    act(() => result.current.setDraft('Hello'));
    rerender();
    const box = screen.getByLabelText('Message');
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('opens the slash menu and runs a command', () => {
    const { result, onCommand, rerender } = setup();
    act(() => result.current.setDraft('/st'));
    rerender();
    expect(screen.getByRole('listbox', { name: 'Commands' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText('Message'), { key: 'Enter' });
    expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ name: 'stop' }));
  });

  it('shows the subject chip and a Stop button while running', () => {
    const { onStop } = setup({ subject: { label: 'CV Screener' }, running: true });
    expect(screen.getByText('CV Screener')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalled();
  });

  it('reads an attached file and can remove it', async () => {
    const { result, rerender } = setup();
    await act(async () => {
      result.current.addFiles([new File(['a,b\n1,2'], 'rates.csv', { type: 'text/csv' })]);
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(result.current.attachments[0]).toMatchObject({ name: 'rates.csv', mime: 'text/csv', progress: 1 });
    expect(result.current.attachments[0].dataB64).toBe(btoa('a,b\n1,2'));
    expect(result.current.canSend).toBe(true);
    rerender();
    fireEvent.click(screen.getByRole('button', { name: 'Remove rates.csv' }));
    rerender();
    expect(result.current.attachments).toHaveLength(0);
  });
});
