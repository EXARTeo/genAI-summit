import { MessagesSquare } from 'lucide-react';
import { PlaceholderView } from './PlaceholderView';

// Stub route view: replaced when the feature (src/features/...) lands.
export default function ChatView() {
  return (
    <PlaceholderView
      title="Chat"
      description="Ask the copilot about a system, a finding or an article."
      icon={<MessagesSquare />}
      emptyTitle="Chat is coming"
      emptyDescription="Conversations stream over AG-UI with every tool call visible."
    />
  );
}
