import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/shared/ui';
import type { ConversationSummary } from '../lib/types';
import { ChatSidebar } from './ChatSidebar';

const conv = (id: string, extra: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id,
  agentSlug: 'assistant',
  title: `Chat ${id}`,
  isArchived: false,
  isPinned: false,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  ...extra,
});

const h = vi.hoisted(() => ({
  listConversationsPage: vi.fn(),
  listPinned: vi.fn(),
  listArchived: vi.fn(),
  renameConversation: vi.fn(),
  setPinned: vi.fn(),
  setArchived: vi.fn(),
  deleteConversation: vi.fn(),
  searchChats: vi.fn(),
}));
vi.mock('../handlers/chat', async (orig) => ({ ...(await orig<object>()), ...h }));

function setup(activeId: string | null = 'b') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TooltipProvider>
          <ChatSidebar activeId={activeId} />
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const section = (name: string) => screen.getByRole('region', { name });

beforeEach(() => {
  for (const fn of Object.values(h)) fn.mockReset();
  h.listPinned.mockResolvedValue({
    items: [conv('p', { isPinned: true, pinnedAt: '2026-11-03T00:00:00Z' })],
  });
  h.listConversationsPage.mockResolvedValue({
    items: [conv('a'), conv('b'), conv('w', { isStreaming: true })],
    page: 1,
    pages: 1,
  });
  h.listArchived.mockResolvedValue({ items: [] });
  h.searchChats.mockResolvedValue([]);
});

describe('ChatSidebar', () => {
  it('shows Pinned and Chats sections, titles only, the open chat marked', async () => {
    setup('b');
    expect(await screen.findByText('Chat p')).toBeInTheDocument();
    expect(within(section('Pinned')).getByText('Chat p')).toBeInTheDocument();
    const chats = section('Chats');
    expect(await within(chats).findByText('Chat a')).toBeInTheDocument();
    expect(within(chats).getByRole('link', { name: 'Chat b' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText('Today')).not.toBeInTheDocument();
  });

  it('shows a spinner in place of the menu while the agent works', async () => {
    setup();
    const row = (await screen.findByText('Chat w')).closest('li')!;
    expect(within(row).getByRole('status', { name: 'Agent is working' })).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Chat actions' })).not.toBeInTheDocument();
  });

  it('folds a section from its heading', async () => {
    const user = setup();
    await screen.findByText('Chat a');
    await user.click(screen.getByRole('button', { name: 'Chats' }));
    await waitFor(() => expect(screen.queryByText('Chat a')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Chats' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('pins and archives from the row menu', async () => {
    h.setPinned.mockResolvedValue(conv('a', { isPinned: true }));
    h.setArchived.mockResolvedValue(conv('a', { isArchived: true }));
    const user = setup();
    const row = (await screen.findByText('Chat a')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'Chat actions' }));
    expect(screen.queryByRole('menuitem', { name: /report/i })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('menuitem', { name: 'Pin' }));
    await waitFor(() => expect(h.setPinned).toHaveBeenCalledWith('a', true));
    await user.click(within(row).getByRole('button', { name: 'Chat actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Archive' }));
    await waitFor(() => expect(h.setArchived).toHaveBeenCalledWith('a', true));
  });

  it('renames inline: Enter saves', async () => {
    h.renameConversation.mockResolvedValue(conv('a', { title: 'New name' }));
    const user = setup();
    const row = (await screen.findByText('Chat a')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'Chat actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    const input = await screen.findByRole('textbox', { name: 'Chat title' });
    expect(input).toHaveValue('Chat a');
    await user.clear(input);
    await user.type(input, 'New name{Enter}');
    await waitFor(() => expect(h.renameConversation).toHaveBeenCalledWith('a', 'New name'));
    await waitFor(() =>
      expect(screen.queryByRole('textbox', { name: 'Chat title' })).not.toBeInTheDocument(),
    );
  });

  it('cancels an inline rename on Escape', async () => {
    const user = setup();
    const row = (await screen.findByText('Chat a')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'Chat actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    await user.type(await screen.findByRole('textbox', { name: 'Chat title' }), 'x{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('textbox', { name: 'Chat title' })).not.toBeInTheDocument(),
    );
    expect(h.renameConversation).not.toHaveBeenCalled();
  });

  it('asks before deleting', async () => {
    h.deleteConversation.mockResolvedValue(undefined);
    const user = setup();
    const row = (await screen.findByText('Chat a')).closest('li')!;
    await user.click(within(row).getByRole('button', { name: 'Chat actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete this chat?' });
    expect(h.deleteConversation).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(h.deleteConversation).toHaveBeenCalledWith('a'));
  });

  it('opens the search panel from the hidden shortcut target and groups results', async () => {
    h.searchChats.mockResolvedValue([
      { kind: 'message', id: 'm1', conversationId: 'a', title: 'Chat a', snippet: 'selection rate' },
      { kind: 'conversation', id: 'b', conversationId: 'b', title: 'Chat b' },
    ]);
    const user = setup();
    await screen.findByText('Chat a');
    document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')!.focus();
    const dialog = await screen.findByRole('dialog', { name: 'Search chats' });
    expect(within(dialog).getByText('Recent chats')).toBeInTheDocument();
    await user.type(within(dialog).getByPlaceholderText(/Search chats, messages/), 'rate');
    expect(await within(dialog).findByText('Messages')).toBeInTheDocument();
    expect(within(dialog).getByText('Chats')).toBeInTheDocument();
    expect(h.searchChats).toHaveBeenCalledWith('rate', expect.anything());
  });
});
