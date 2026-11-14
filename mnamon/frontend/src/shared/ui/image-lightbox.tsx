/**
 * The full-screen image viewer (magenticx `shared/ui/ImageLightbox.tsx`), shared by every surface
 * that expands an image: chat attachments and composer files, generated images, system folders.
 *
 * Built on Radix Dialog (focus trap, Escape, focus back to the opener, `aria-modal`) with
 * magenticx's panel motion through framer-motion (`panelBackdrop` / `panelContent`; reduced
 * motion only fades). Beyond magenticx: zoom (buttons, wheel, double-click, +/−/0 keys) with drag
 * to pan, and prev / next between the images of one message or list (arrows, ←/→).
 *
 * Callers keep it mounted and pass `index={null}` to close; the last image stays on screen while
 * the layer fades out. Backdrop click closes.
 */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, Download, X, ZoomIn, ZoomOut } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type SyntheticEvent,
  type WheelEvent,
} from 'react';
import { downloadName, triggerBrowserDownload } from '@/shared/lib/files';
import { imageSwap, panelBackdrop, panelContent } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Tooltip } from './tooltip';

export interface LightboxImage {
  src: string;
  name: string;
  alt?: string;
  mime?: string | null;
}

export interface ImageLightboxProps {
  images: LightboxImage[];
  /** The image shown; null closes. */
  index: number | null;
  onIndexChange?: (index: number) => void;
  onClose: () => void;
  /** Overrides the default download (fetch the src, save it under its name). */
  onDownload?: (image: LightboxImage, index: number) => void;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 5;
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

const CONTROL =
  'grid size-9 shrink-0 place-items-center rounded-full border border-border/60 bg-surface/95 text-text shadow-pop transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-[18px]';

async function defaultDownload(image: LightboxImage) {
  // Every src kind (data:, blob:, same-origin URL) goes through a Blob so the name is kept.
  try {
    const res = await fetch(image.src);
    if (!res.ok) throw new Error(String(res.status));
    const blob = await res.blob();
    triggerBrowserDownload(blob, downloadName(image.name, image.mime ?? blob.type));
  } catch {
    const a = document.createElement('a');
    a.href = image.src;
    a.download = downloadName(image.name, image.mime);
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}

export function ImageLightbox({ images, index, onIndexChange, onClose, onDownload }: ImageLightboxProps) {
  const open = index != null && Boolean(images[index]);
  // Keep the last image while the layer leaves.
  const last = useRef<{ image: LightboxImage; index: number } | null>(null);
  if (open) last.current = { image: images[index!], index: index! };
  const shown = last.current;

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const [saving, setSaving] = useState(false);

  const reset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);
  useEffect(reset, [index, reset]);

  const count = images.length;
  const go = useCallback(
    (delta: number) => {
      if (index == null || count < 2) return;
      onIndexChange?.((index + delta + count) % count);
    },
    [count, index, onIndexChange],
  );
  const zoomBy = useCallback((factor: number) => {
    setZoom((z) => {
      const next = clamp(z * factor, MIN_ZOOM, MAX_ZOOM);
      if (next === 1) setPan({ x: 0, y: 0 });
      return next;
    });
  }, []);

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') go(1);
    else if (e.key === 'ArrowLeft') go(-1);
    else if (e.key === '+' || e.key === '=') zoomBy(1.4);
    else if (e.key === '-') zoomBy(1 / 1.4);
    else if (e.key === '0') reset();
    else return;
    e.preventDefault();
  };

  const onWheel = (e: WheelEvent) => {
    zoomBy(Math.exp(-e.deltaY * 0.0015));
  };
  const onPointerDown = (e: PointerEvent) => {
    if (zoom <= 1 || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
    setDragging(true);
  };
  const onPointerMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setPan({ x: d.px + (e.clientX - d.x), y: d.py + (e.clientY - d.y) });
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };

  const download = async () => {
    if (!shown) return;
    if (onDownload) return onDownload(shown.image, shown.index);
    setSaving(true);
    await defaultDownload(shown.image);
    setSaving(false);
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <AnimatePresence>
        {open && shown && (
          <DialogPrimitive.Portal forceMount>
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-50 bg-scrim-strong"
                variants={panelBackdrop}
                initial="initial"
                animate="animate"
                exit="exit"
              />
            </DialogPrimitive.Overlay>
            <DialogPrimitive.Content
              forceMount
              aria-describedby={undefined}
              // Escape closes this layer only (not the chat's Esc-to-stop behind it).
              onEscapeKeyDown={(e) => e.stopPropagation()}
              onKeyDown={onKeyDown}
              className="fixed inset-0 z-50 flex items-center justify-center outline-none"
              onClick={onClose}
              data-testid="image-lightbox"
            >
              <DialogPrimitive.Title className="sr-only">{shown.image.name}</DialogPrimitive.Title>

              {/* Top bar: name + counter on the left, zoom, download and close on the right. */}
              <motion.div
                className="absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-2 p-3 sm:p-4"
                variants={panelBackdrop}
                initial="initial"
                animate="animate"
                exit="exit"
              >
                <div
                  onClick={stop}
                  className="flex h-9 min-w-0 items-center gap-2 rounded-full border border-border/60 bg-surface/95 px-3.5 text-sm text-text shadow-pop"
                >
                  <span className="truncate font-medium">{shown.image.name}</span>
                  {count > 1 && (
                    <span className="num shrink-0 text-xs text-muted" aria-live="polite">
                      {shown.index + 1} / {count}
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1.5" onClick={stop}>
                  <Tooltip content="Zoom out (−)" side="bottom">
                    <button
                      type="button"
                      className={cn(CONTROL, 'hidden sm:grid')}
                      onClick={() => zoomBy(1 / 1.4)}
                      disabled={zoom <= MIN_ZOOM}
                      aria-label="Zoom out"
                    >
                      <ZoomOut />
                    </button>
                  </Tooltip>
                  <Tooltip content="Reset zoom (0)" side="bottom">
                    <button
                      type="button"
                      onClick={reset}
                      aria-label={`Zoom ${Math.round(zoom * 100)} percent, reset`}
                      className="num hidden h-9 min-w-[3.5rem] place-items-center rounded-full border border-border/60 bg-surface/95 px-2 text-xs font-medium text-text shadow-pop transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid"
                    >
                      {Math.round(zoom * 100)}%
                    </button>
                  </Tooltip>
                  <Tooltip content="Zoom in (+)" side="bottom">
                    <button
                      type="button"
                      className={CONTROL}
                      onClick={() => (zoom >= MAX_ZOOM ? reset() : zoomBy(1.4))}
                      aria-label={zoom >= MAX_ZOOM ? 'Reset zoom' : 'Zoom in'}
                    >
                      <ZoomIn />
                    </button>
                  </Tooltip>
                  <Tooltip content="Download" side="bottom">
                    <button
                      type="button"
                      className={CONTROL}
                      onClick={() => void download()}
                      disabled={saving}
                      aria-label="Download image"
                    >
                      <Download />
                    </button>
                  </Tooltip>
                  <Tooltip content="Close (Esc)" side="bottom">
                    <DialogPrimitive.Close className={CONTROL} aria-label="Close image preview">
                      <X />
                    </DialogPrimitive.Close>
                  </Tooltip>
                </div>
              </motion.div>

              {count > 1 && (
                <>
                  <button
                    type="button"
                    aria-label="Previous image"
                    onClick={(e) => {
                      stop(e);
                      go(-1);
                    }}
                    className={cn(CONTROL, 'absolute left-2 top-1/2 z-10 size-10 -translate-y-1/2 sm:left-4')}
                  >
                    <ChevronLeft />
                  </button>
                  <button
                    type="button"
                    aria-label="Next image"
                    onClick={(e) => {
                      stop(e);
                      go(1);
                    }}
                    className={cn(
                      CONTROL,
                      'absolute right-2 top-1/2 z-10 size-10 -translate-y-1/2 sm:right-4',
                    )}
                  >
                    <ChevronRight />
                  </button>
                </>
              )}

              <motion.div
                className="relative flex h-[calc(100dvh-8rem)] w-[calc(100vw-1.5rem)] items-center justify-center sm:w-[calc(100vw-9rem)]"
                variants={panelContent}
                initial="initial"
                animate="animate"
                exit="exit"
              >
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.img
                    key={shown.image.src}
                    src={shown.image.src}
                    alt={shown.image.alt ?? shown.image.name}
                    draggable={false}
                    variants={imageSwap}
                    initial="initial"
                    animate="animate"
                    exit="exit"
                    onClick={stop}
                    onWheel={onWheel}
                    onDoubleClick={() => (zoom > 1 ? reset() : setZoom(2))}
                    onPointerDown={onPointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                    style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
                    className={cn(
                      'max-h-full max-w-full select-none rounded-lg object-contain shadow-pop',
                      zoom > 1 ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : 'cursor-zoom-in',
                      !dragging && 'transition-transform duration-150 ease-out motion-reduce:transition-none',
                    )}
                  />
                </AnimatePresence>
              </motion.div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        )}
      </AnimatePresence>
    </DialogPrimitive.Root>
  );
}
