import { MessageSquareText } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/shared/ui';
import { chatRoutes } from '../lib/routes';

/** "Chat about this": opens a new chat scoped to a system and/or an audit (`/chat?system=&audit=`). */
export function ChatAboutButton({
  systemId,
  auditId,
  label = 'Chat about this',
}: {
  systemId?: string | null;
  auditId?: string | null;
  label?: string;
}) {
  return (
    <Button asChild variant="secondary">
      <Link to={chatRoutes.about({ systemId, auditId })}>
        <MessageSquareText />
        {label}
      </Link>
    </Button>
  );
}
