# Verifying layout defects (you cannot do it in jsdom)

## When
Any report of the form "it's not responsive", "X is hidden behind Y", "sizes look hardcoded",
"content is cut off". Unit tests are near-worthless here: **jsdom has no layout engine**, so
every `getBoundingClientRect()` returns zeros and every assertion passes.

## Method
1. Build the app and serve it statically **with SPA history fallback**.
2. Drive it with Playwright/Chromium at several viewports — include a **short** one
   (~640-780px tall). Most layout bugs are vertical, and desktop dev machines are tall.
3. Stub only HTTP, so real components with real data volumes render.
4. Assert on measurements, not on the DOM: element `bottom <= innerHeight`,
   `elementFromPoint(centre)` is the control you think it is, no pane has zero width.
5. **Screenshot and look at it.** A blank screenshot at scroll-bottom told me in one glance
   what twenty numeric probes had not.

## Traps this caught
- **`flex-shrink: 1` is the default.** A toolbar/command row in a flex column will be
  crushed below its content height while a `flexGrow: 1` sibling keeps its space. The row
  that must always be visible needs `flexShrink: 0`. A `minHeight: 0` helper (added to let
  panes shrink) makes this *worse* by removing the min-content floor.
- **`overflow: hidden` does not clip `position: absolute` descendants** unless the element
  is their containing block. A `100vh; overflow: hidden` app shell that is `position: static`
  will leak visually-hidden a11y spans and gain hundreds of px of phantom scroll. Add
  `position: relative`.
- **Contradictory measurements mean the measurement is wrong.** `documentElement.scrollHeight`
  read 1684 while html/body/#root all read 720. Confirm with a second, independent signal
  (`window.scrollY` after a `scrollTo`, plus a screenshot) before theorising.
- **Check reachability before escalating.** "Content is cut off" may just be a scroll
  container. Read `overflowY` and `scrollHeight` — cramped is a UX problem, unreachable is a
  blocking bug. They deserve different responses.

## Always
Count the test baseline before and after. A flaky test you *triggered* is a test you own:
stash your changes and re-run the original tree to find out which it is.

## Two more traps (learned the hard way)

- **A pane measured EMPTY tells you nothing about that pane FULL.** Flex children without
  `flexGrow` size to their CONTENT. A pane whose empty state is a long paragraph looks
  perfect forever, then collapses the moment real, shorter content arrives. Always drive at
  least one test with realistic content, not just the initial state.
- **An unfaithful stub does not merely miss bugs — it invents them.** A stubbed event that
  omitted two optional-looking fields rendered a step as "NaN." and looked exactly like a
  product defect. Before filing, read the SERVER's emitter and match the payload. If the
  product looks broken only under your stub, the stub is the suspect.
- **Prove a new regression test can fail.** Revert the one line it guards, rebuild, watch it
  go red with the real number, then restore. A green test that has never failed is decoration.
