# Website redesign v3 — design QA

## Inputs

- User correction reference: `Screenshot 2026-09-02 at 20.33.04.png` (2256×522)
- Prototype capture: `prototype-home-final.png` (1440×930)
- Side-by-side comparison: `reference-vs-prototype-final.png`
- Inner-page seam check: `workflows-seam-final.png` (1440×930)
- Screenshot-shell check: `home-framing-final.png` (1440×930)
- Footer alignment check: `footer-spacing-final.png` (1440×930)
- Responsive check: 390×844

## Direction

The rejected pass put too many independent rounded containers on the page and let the floating header
occupy a separate white strip. This revision treats the site as one continuous editorial surface: the
homepage color now runs behind the fixed blurred header, product chapters become full-width color fields,
and borders are reserved for screenshots, controls, and quiet structural dividers. The same system now
continues across Workflows, Plugins, plugin details, documentation, mobile navigation, the 404 page, and
the footer instead of stopping at the homepage.

## Checks

- The header is fixed above page content, fully rounded, translucent, blurred, and shadow-free. It no longer
  creates an opaque band that cuts off the homepage gradient.
- Product is active only on the locale homepage; Docs, Plugins, and Workflows use their own path prefixes.
- Infinite Canvas is no longer a standalone navigation item and remains discoverable in the product story
  and documentation.
- The first product capture begins inside the opening viewport on mobile and follows the hero without an
  artificial browser-chrome wrapper.
- Product captures keep their native aspect ratios and remain legible instead of being cropped into small
  decorative cards.
- The four core capabilities use edge-to-edge color fields, alternating editorial composition, and oversized
  chapter numerals instead of four rounded cards.
- Workflows and Plugins use open page headers, full-width product proof, hairline-separated rows, and dark
  emphasis bands; plugin details and docs share the same lighter hierarchy.
- The inner-page radial background begins at the top of the viewport and remains visible behind the floating
  header, without a separate paper-colored strip.
- Homepage product captures render without a second border, background, or rounded shell around the window
  already present in the supplied image.
- The tightly cropped wordmark aligns with the footer copy, and link groups use a more relaxed vertical rhythm.
- The 390 px layout keeps both primary actions on screen, preserves headline hierarchy, and turns navigation
  into a functional full-screen menu.
- The mobile menu is rendered outside the blurred header containing block, so it fills the viewport rather
  than being clipped to the pill.
- The mobile menu replaces stacked framed controls with simple divider rows and a single primary pill.
- Light and dark theme tokens remain supported; no drop shadows were introduced.
- The production build succeeds and the browser console contains no warnings or errors during the tested
  homepage, Workflows, Plugins, plugin-detail, and documentation routes.

final result: passed
