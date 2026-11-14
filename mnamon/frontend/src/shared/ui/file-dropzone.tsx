import { UploadCloud } from 'lucide-react';
import { useRef, useState, type DragEvent, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export interface FileDropzoneProps {
  onFiles: (files: File[]) => void;
  /** `accept` attribute, e.g. ".md,.yaml,.csv,.pdf". */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  title?: ReactNode;
  hint?: ReactNode;
  className?: string;
}

/** Drag-and-drop (or click) file picker. */
export function FileDropzone({
  onFiles,
  accept,
  multiple = true,
  disabled,
  title = 'Drop files here or click to browse',
  hint,
  className,
}: FileDropzoneProps) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(multiple ? files : files.slice(0, 1));
  };

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && !disabled) {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border px-6 py-8 text-center transition-all duration-200',
        'hover:border-primary/50 hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        over && 'scale-[1.01] border-primary bg-primary/[0.06]',
        disabled && 'pointer-events-none opacity-50',
        className,
      )}
    >
      <div
        className={cn(
          'grid size-11 place-items-center rounded-xl bg-primary/10 text-primary transition-transform duration-200',
          over && '-translate-y-1',
        )}
      >
        <UploadCloud className="size-5" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      <input
        ref={input}
        type="file"
        className="hidden"
        accept={accept}
        multiple={multiple}
        data-testid="file-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = '';
        }}
      />
    </div>
  );
}
