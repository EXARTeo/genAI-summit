import { Compass } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { Button, EmptyState } from '@/shared/ui';

export default function NotFoundView() {
  const { pathname } = useLocation();
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <EmptyState
        icon={<Compass />}
        title="Page not found"
        description={
          <>
            Nothing lives at <code className="font-mono text-text">{pathname}</code>. It may have moved.
          </>
        }
        action={
          <Button asChild>
            <Link to="/">Back to home</Link>
          </Button>
        }
        className="border-none"
      />
    </div>
  );
}
