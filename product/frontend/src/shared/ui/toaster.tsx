import { Toaster as Sonner, toast } from 'sonner';
import { useThemeStore } from '@/shared/stores/theme';

/** Mount once (WorkspaceShell). Use `toast.success(...)`, `toast.error(...)`, `toast.promise(...)`. */
export function Toaster() {
  const resolved = useThemeStore((s) => s.resolved);
  return <Sonner theme={resolved} position="bottom-right" closeButton richColors={false} duration={4000} />;
}

export { toast };
