/** Mock routes for the chat (conversations, messages, attachments, inference, search). */
import { writeFile } from '@/shared/lib/mocks/fixtures/systems';
import { MockResponse, mockError, type MockRoute } from '@/shared/lib/mocks/types';
import { blobs, mockChat } from './mockRuns';
import type { InferenceStartPayload, ResumePayload } from './types';

const page = <T>(items: T[]) => ({ items, total: items.length, page: 1, size: items.length, pages: 1 });

const MOCK_AGENTS = [
  {
    slug: 'assistant',
    name: 'Copilot',
    description: 'Answers questions about your systems, audits and the AI Act.',
    default: true,
  },
  {
    slug: 'auditor',
    name: 'Auditor',
    description: 'Plans and runs a compliance audit of one system, step by step.',
  },
];

function blobResponse(blobId: string) {
  const blob = blobs.get(blobId);
  if (!blob) return mockError(404, 'File not found');
  const bytes = Uint8Array.from(atob(blob.b64), (c) => c.charCodeAt(0));
  return new MockResponse(200, new Blob([bytes], { type: blob.mime }), blob.mime);
}

function patchOr404(id: string, patch: Parameters<typeof mockChat.patch>[1]) {
  return mockChat.patch(id, patch) ?? mockError(404, 'Conversation not found');
}

export const chatRoutes: MockRoute[] = [
  { method: 'GET', path: '/v1/agents', handler: () => MOCK_AGENTS },
  { method: 'GET', path: '/v1/conversations', handler: () => page(mockChat.list('recent')) },
  { method: 'GET', path: '/v1/conversations/pinned', handler: () => page(mockChat.list('pinned')) },
  { method: 'GET', path: '/v1/conversations/archived', handler: () => page(mockChat.list('archived')) },
  {
    method: 'GET',
    path: '/v1/conversations/:id',
    handler: ({ params }) => mockChat.get(params.id) ?? mockError(404, 'Conversation not found'),
  },
  {
    method: 'DELETE',
    path: '/v1/conversations/:id',
    handler: ({ params }) => void mockChat.remove(params.id),
  },
  {
    method: 'PATCH',
    path: '/v1/conversations/:id/title',
    handler: ({ params, body }) =>
      patchOr404(params.id, { title: String((body as { title?: string }).title ?? '').trim() }),
  },
  {
    method: 'PATCH',
    path: '/v1/conversations/:id/pin',
    handler: ({ params }) => patchOr404(params.id, { isPinned: true, pinnedAt: new Date().toISOString() }),
  },
  {
    method: 'PATCH',
    path: '/v1/conversations/:id/unpin',
    handler: ({ params }) => patchOr404(params.id, { isPinned: false, pinnedAt: null }),
  },
  {
    method: 'PATCH',
    path: '/v1/conversations/:id/archive',
    handler: ({ params }) =>
      patchOr404(params.id, { isArchived: true, archivedAt: new Date().toISOString() }),
  },
  {
    method: 'PATCH',
    path: '/v1/conversations/:id/unarchive',
    handler: ({ params }) => patchOr404(params.id, { isArchived: false, archivedAt: null }),
  },
  { method: 'GET', path: '/v1/conversations/:id/tasks', handler: () => [] },
  {
    method: 'POST',
    path: '/v1/messages/:conv/:msg/like',
    handler: ({ params }) => mockChat.rate(params.conv, params.msg, true),
  },
  {
    method: 'POST',
    path: '/v1/messages/:conv/:msg/dislike',
    handler: ({ params }) => mockChat.rate(params.conv, params.msg, false),
  },
  {
    method: 'POST',
    path: '/v1/inference/runs/start',
    handler: ({ body }) => {
      const started = mockChat.start(body as InferenceStartPayload);
      return started ? new MockResponse(201, started) : mockError(404, 'Conversation not found');
    },
  },
  { method: 'GET', path: '/v1/inference/runs', handler: () => mockChat.activeRuns() },
  {
    method: 'POST',
    path: '/v1/inference/runs/:id/cancel',
    handler: ({ params }) => mockChat.cancel(params.id) ?? mockError(404, 'Inference run not found'),
  },
  {
    method: 'POST',
    path: '/v1/inference/runs/:id/resume',
    handler: ({ params, body }) =>
      mockChat.resume(params.id, body as ResumePayload) ?? mockError(409, 'The run is not paused.'),
  },
  { method: 'DELETE', path: '/v1/inference/conversations/:id/queued-message', handler: () => undefined },
  { method: 'GET', path: '/v1/search', handler: ({ query }) => mockChat.search(query.get('q') ?? '') },
  {
    method: 'GET',
    path: '/v1/attachments/download/:conv/:msg/:blob',
    handler: ({ params }) => blobResponse(params.blob),
  },
  {
    method: 'GET',
    path: '/v1/attachments/preview/:conv/:msg/:blob',
    handler: ({ params }) => blobResponse(params.blob),
  },
  {
    method: 'POST',
    path: '/v1/systems/:systemId/files/from-attachment',
    handler: ({ params, body }) => {
      const { attachmentId, path } = body as { attachmentId: string; path?: string | null };
      const attachment = mockChat.findAttachment(attachmentId);
      if (!attachment) return mockError(404, 'Attachment not found');
      const blob = attachment.blobId ? blobs.get(attachment.blobId) : undefined;
      let text = `(binary file ${attachment.name})`;
      if (blob && /^(text\/|application\/(json|yaml))/.test(blob.mime)) {
        text = decodeURIComponent(escape(atob(blob.b64)));
      }
      const target = path || `uploads/${attachment.name}`;
      return new MockResponse(201, writeFile(params.systemId, target, text, 'user:chat', 'Saved from chat'));
    },
  },
];
