# Global Status Indicator (iOS-style Footer Pill) Plan

## Overview
Replace the existing page footers (the "3 dots") and all text with a global, iOS home indicator-style pill at the bottom center of the screen. This pill will visually communicate the current state of the application (e.g., idle, processing, error, success) by changing colors and animating when the site is actively performing a task.

## 1. Global State Management
To control the color and animation of the footer pill globally from any page or component, we need a global state.
- **Approach**: Create a lightweight React Context or use Zustand (if already available in the project) to expose a `useAppStatus` hook.
- **State Properties**:
  - `status`: `'idle' | 'loading' | 'success' | 'error'`
  - `message` (optional): For screen readers or tooltips.

## 2. Component Design (`GlobalFooterPill.tsx`)
Create a new component in `src/components/global-footer-pill.tsx`.

### Structure & Positioning
- Use `fixed bottom-4 left-1/2 -translate-x-1/2 z-50` to lock the pill at the bottom center of the viewport, above all other content.
- Give it dimensions similar to an iOS home bar: `w-32 h-1.5` or `w-40 h-2`.
- Apply `rounded-full` to achieve the pill/capsule shape.

### Color Mapping
Tie Tailwind background colors to the current status state:
- `'idle'`: `bg-muted` or `bg-zinc-700/50` (subtle and unobtrusive).
- `'loading'`: A vibrant color like `bg-accent-blue` or a gradient.
- `'success'`: `bg-accent-green`.
- `'error'`: `bg-accent-red`.

### Animation (Scrolling Effect)
When the status is `'loading'` or the app is actively performing a task:
- Apply a horizontal scrolling gradient or a pulsing animation to indicate activity.
- **Tailwind configuration (`tailwind.config.ts`)**:
  - Add a custom animation: `scroll-bg: 'scroll-bg 1.5s linear infinite'`
  - Add keyframes:
    ```css
    @keyframes scroll-bg {
      0% { background-position: 200% center; }
      100% { background-position: -200% center; }
    }
    ```
- **Component styling for busy state**:
  - Apply `bg-[linear-gradient(90deg,theme(colors.blue.500),theme(colors.blue.300),theme(colors.blue.500))]`
  - Add `bg-[length:200%_auto]`
  - Add the `animate-scroll-bg` class.

## 3. Removing the Old Footer
- Search across the `src/app` directories (e.g., `page.tsx`, `dashboard/page.tsx`, etc.) to remove the existing "3 dots" indicators or legacy static footer elements.
- Ensure no conflicting padding exists at the bottom of the main layout arrays that might overlap poorly with the new fixed pill.

## 4. Integration
Import the new `GlobalFooterPill` into the root layout `src/app/layout.tsx`.

```tsx
// src/app/layout.tsx
import { GlobalFooterPill } from "@/components/global-footer-pill"
import { AppStatusProvider } from "@/lib/app-status-context" // if using Context

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="...">
        <Providers>
          <AppStatusProvider>
             {children}
             <GlobalFooterPill />
             <Toaster />
          </AppStatusProvider>
        </Providers>
      </body>
    </html>
  );
}
```

## 5. Implementation Steps
1. Create state management hook/context (`use-app-status.ts`).
2. Add custom Tailwind animation keyframes to the stylesheet or tailwind config.
3. Create `GlobalFooterPill.tsx` using Tailwind classes for shape and dynamic colors.
4. Mount it in `src/app/layout.tsx`.
5. Remove the old "3 dots" footer implementations from local page files.
6. Test status updates from random pages to ensure the color transitions and scrolling animations trigger effectively.
