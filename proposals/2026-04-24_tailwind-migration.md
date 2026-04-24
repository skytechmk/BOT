# Proposal: Tailwind CSS Grid Implementation

## Context & Problem
The current frontend (`dashboard/index.html` and components) relies on massive, deeply nested inline style strings (e.g., `<div style="display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px">`). 

This causes three issues:
1. **DOM Bloat**: Inflates HTTP payload size, degrading First Contentful Paint.
2. **Maintenance Nightmare**: CSS cannot be cascaded cleanly, forcing duplicate logic.
3. **Mobile Unreadiness**: Media queries cannot be applied to inline styles, meaning components squash on mobile devices instead of stacking gracefully.

## Proposed Architecture: Tailwind CSS Standalone (Vite Toolchain)

Given the project uses a standard vanilla JS / HTML structure, wrapping the frontend in a lightweight Vite build step with Tailwind CSS allows us to compile an optimized, minified `main.css` file while keeping the HTML templates clean.

### 1. Toolchain Setup
Initialize `/dashboard` with standard Node tools:
```bash
cd dashboard
npm init -y
npm install -D tailwindcss postcss autoprefixer vite
npx tailwindcss init -p
```

### 2. Implementation Strategy (DOM Refactor)
Replace inline dictionaries with Tailwind atomic classes:

**Before (Legacy Inline):**
```html
<header style="height:auto;flex-direction:column;align-items:stretch;padding:0;gap:0">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:0 24px;height:56px">
```

**After (Tailwind + Mobile Responsive Formats):**
```html
<header class="h-auto flex-col items-stretch p-0 gap-0">
    <div class="flex items-center justify-between px-6 h-14 md:px-8">
```

### 3. Grid System
Establish a strict 12-column grid layout across the platform:
- Data tables span `col-span-12` on mobile, but `col-span-8` on desktop.
- Live context widgets span `col-span-12` on mobile, stacking beneath the table, but `col-span-4` on desktop.

## Risk Assessment
**Low Risk / High Effort**: Changing styles is mathematically safe and doesn't affect trading logic, but requires touching over 1,700 lines of HTML. It should be performed in a dedicated `frontend-v2` branch.
