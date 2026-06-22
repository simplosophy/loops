# Frontend Page Optimization Plan

> Date: 2026-06-22
> Scope: Optimize the HLP documentation site frontend end to end.

## Goal

Make the public site communicate the HLP-first positioning faster and more
clearly across desktop and mobile.

## Changes

- Reorder the homepage so the first screen emphasizes HLP value, scope, and
  primary reading paths before the integration diagram.
- Add a concise scope panel for what HLP defines, routes to, and does not
  replace.
- Add first-class object and integration contract overview sections.
- Improve overview page scanability with a HLP summary hero and three key
  positioning cards.
- Normalize dark theme tokens and responsive card styles so custom sections
  render consistently instead of falling back to default link styling.

## Verification

- Build the VitePress site.
- Run the site verification script.
- Run Python tests to confirm docs/frontend changes do not affect the HLP
  reference implementation.
- Use browser screenshots for desktop and mobile homepage, plus desktop
  overview.
