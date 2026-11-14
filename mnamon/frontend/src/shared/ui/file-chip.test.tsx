import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FileChip } from './file-chip';
import { ImageLightbox } from './image-lightbox';
import { TooltipProvider } from './tooltip';

const wrap = (ui: React.ReactElement) => render(<TooltipProvider>{ui}</TooltipProvider>);

describe('FileChip', () => {
  it('composer: shows type and size, opens and removes', () => {
    const onOpen = vi.fn();
    const onRemove = vi.fn();
    wrap(
      <FileChip variant="composer" name="model-card.pdf" size={2048} onOpen={onOpen} onRemove={onRemove} />,
    );
    expect(screen.getByText('PDF · 2.0 KB')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview model-card.pdf' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove model-card.pdf' }));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onRemove).toHaveBeenCalledOnce();
  });

  it('composer: shows read progress and blocks opening while busy', () => {
    const onOpen = vi.fn();
    wrap(<FileChip variant="composer" name="a.csv" size={10} progress={0.4} onOpen={onOpen} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
    expect(screen.getByText('Reading… 40%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview a.csv' })).toBeDisabled();
  });

  it('composer: an error replaces the subtitle', () => {
    wrap(<FileChip variant="composer" name="a.csv" error="Could not read the file" />);
    expect(screen.getByText('Could not read the file')).toBeInTheDocument();
  });

  it('message: click previews, or downloads when there is no preview', () => {
    const onOpen = vi.fn();
    const onDownload = vi.fn();
    const { rerender } = wrap(
      <FileChip name="notes.md" mime="text/markdown" onOpen={onOpen} onDownload={onDownload} />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview notes.md' })[0]);
    expect(onOpen).toHaveBeenCalledOnce();
    rerender(
      <TooltipProvider>
        <FileChip name="model.pkl" onDownload={onDownload} />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getAllByRole('button', { name: 'Download model.pkl' })[0]);
    expect(onDownload).toHaveBeenCalledOnce();
  });
});

describe('ImageLightbox', () => {
  const images = [
    { src: 'data:image/png;base64,AA==', name: 'one.png' },
    { src: 'data:image/png;base64,AQ==', name: 'two.png' },
  ];

  it('steps with the arrows and closes', () => {
    const onIndexChange = vi.fn();
    const onClose = vi.fn();
    wrap(<ImageLightbox images={images} index={0} onIndexChange={onIndexChange} onClose={onClose} />);
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId('image-lightbox'), { key: 'ArrowRight' });
    expect(onIndexChange).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole('button', { name: 'Previous image' }));
    expect(onIndexChange).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByRole('button', { name: /Zoom 140 percent/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close image preview' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders nothing when closed', () => {
    wrap(<ImageLightbox images={images} index={null} onClose={() => undefined} />);
    expect(screen.queryByTestId('image-lightbox')).toBeNull();
  });
});
