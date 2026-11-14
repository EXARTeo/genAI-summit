import { QueryClientProvider } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ErrorBoundary } from './error_boundary';
import { queryClient } from './shared/lib/query-client';
import { applyTheme, useThemeStore } from './shared/stores/theme';
import { TooltipProvider } from './shared/ui/tooltip';
import './index.css';

// theme-init.js already set data-theme; keep it in sync with the store.
applyTheme(useThemeStore.getState().resolved);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <MotionConfig reducedMotion="user">
          <TooltipProvider delayDuration={250}>
            <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
              <App />
            </BrowserRouter>
          </TooltipProvider>
        </MotionConfig>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
