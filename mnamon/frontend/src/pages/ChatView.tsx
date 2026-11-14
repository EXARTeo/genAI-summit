import { useParams } from 'react-router-dom';
import { SidebarExtra } from '@/app/sidebarSlot';
import { TopbarExtra } from '@/app/topbarSlot';
import { ChatSidebar } from '@/features/chat/components/ChatSidebar';
import { ChatWorkspace } from '@/features/chat/components/ChatWorkspace';

/**
 * `/chat` (new chat; `?system=` / `?audit=` scope it) and `/chat/:conversationId`.
 * The conversation list goes into the shell's sidebar rail (below the nav) and the chat header
 * (agent picker, subject, actions) into the top bar, like magenticx.
 */
export default function ChatView() {
  const params = useParams();
  const id = params['*'] ? decodeURIComponent(params['*'].split('/')[0]) : null;
  return (
    <>
      <SidebarExtra>
        <ChatSidebar activeId={id || null} />
      </SidebarExtra>
      <ChatWorkspace conversationId={id || null} HeaderSlot={TopbarExtra} />
    </>
  );
}
