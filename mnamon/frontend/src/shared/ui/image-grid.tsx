/**
 * In-message image thumbnails (magenticx `message_parts/MessageAttachments.tsx`, images half): a
 * two-column grid of cover-cropped tiles, an odd last image spanning both columns, an eye on hover.
 * A tile opens the shared `ImageLightbox`, which steps through every image of the grid. An optional
 * ⋯ menu per tile carries extra actions (Download, "Save to <system> folder").
 */
import { Eye, MoreHorizontal } from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu } from './dropdown-menu';
import type { FileAction } from './file-chip';
import { ImageLightbox, type LightboxImage } from './image-lightbox';

export interface GridImage extends LightboxImage {
  id: string;
  actions?: FileAction[];
}

export interface ImageGridProps {
  images: GridImage[];
  align?: 'start' | 'end';
  /** Overrides the lightbox's download. */
  onDownload?: (image: GridImage, index: number) => void;
  className?: string;
}

export function ImageGrid({ images, align = 'start', onDownload, className }: ImageGridProps) {
  const [index, setIndex] = useState<number | null>(null);
  if (!images.length) return null;
  const single = images.length === 1;
  return (
    <>
      <div
        className={cn(
          'grid w-[min(100%,20.75rem)] grid-cols-2 gap-3 md:w-[24.75rem]',
          align === 'end' && 'self-end',
          className,
        )}
        data-testid="image-grid"
      >
        {images.map((img, i) => {
          const wide = images.length % 2 === 1 && i === images.length - 1;
          return (
            <div key={img.id} className={cn('group/img relative', wide && 'col-span-2')}>
              <button
                type="button"
                onClick={() => setIndex(i)}
                aria-label={`View ${img.name}`}
                className="block w-full cursor-zoom-in overflow-hidden rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <img
                  src={img.src}
                  alt={img.alt ?? img.name}
                  loading="lazy"
                  className={cn(
                    'w-full rounded-xl bg-surface-sunken object-cover transition-transform duration-200 group-hover/img:scale-[1.02] motion-reduce:transition-none',
                    single ? 'h-44 md:h-52' : 'h-28 md:h-32',
                  )}
                />
                <span className="pointer-events-none absolute inset-0 grid place-items-center rounded-xl bg-scrim opacity-0 transition-opacity duration-200 group-focus-within/img:opacity-100 group-hover/img:opacity-100">
                  <span className="grid size-8 place-items-center rounded-full border border-border/50 bg-background/95 text-text shadow-pop">
                    <Eye className="size-4" aria-hidden />
                  </span>
                </span>
              </button>
              {(img.actions?.length ?? 0) > 0 && (
                <div className="absolute right-1.5 top-1.5">
                  <DropdownMenu
                    items={img.actions!.map((a) => ({
                      label: a.label,
                      icon: a.icon,
                      onSelect: a.onSelect,
                      disabled: a.disabled,
                    }))}
                    trigger={
                      <button
                        type="button"
                        aria-label={`Actions for ${img.name}`}
                        className="grid size-7 place-items-center rounded-full border border-border/50 bg-background/90 text-text opacity-0 shadow-sm transition-opacity hover:bg-background focus-visible:opacity-100 group-hover/img:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
                      >
                        <MoreHorizontal className="size-4" />
                      </button>
                    }
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
      <ImageLightbox
        images={images}
        index={index}
        onIndexChange={setIndex}
        onClose={() => setIndex(null)}
        onDownload={onDownload ? (img, i) => onDownload(images[i] ?? (img as GridImage), i) : undefined}
      />
    </>
  );
}
