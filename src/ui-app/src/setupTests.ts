// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import userEvent from '@testing-library/user-event';
import { act } from '@testing-library/react';

if (typeof (userEvent as { setup?: () => unknown }).setup !== 'function') {
  (userEvent as { setup?: () => unknown }).setup = () => {
    const wrap = <T extends (...args: any[]) => any>(fn: T) => async (...args: Parameters<T>) => {
      let result: ReturnType<T>;
      await act(async () => {
        result = await fn(...args);
      });
      return result!;
    };

    return {
      ...userEvent,
      click: wrap(userEvent.click),
      dblClick: wrap(userEvent.dblClick),
      type: wrap(userEvent.type),
      clear: wrap(userEvent.clear),
      tab: wrap(userEvent.tab),
      hover: wrap(userEvent.hover),
      unhover: wrap(userEvent.unhover),
      upload: wrap(userEvent.upload),
      selectOptions: wrap(userEvent.selectOptions),
      deselectOptions: wrap(userEvent.deselectOptions),
      paste: wrap(userEvent.paste),
      keyboard: wrap(userEvent.keyboard),
    };
  };
}

/**
 * jsdom does not implement ResizeObserver, which `CopilotHarness` uses to size
 * the work surface against whatever chrome is above it. Every real browser has
 * it, so this belongs in the test environment rather than being guarded for in
 * component code — a component that quietly skips its own layout when an API is
 * missing would hide exactly the bug this observer exists to prevent.
 *
 * The stub records observers without firing them. The initial measurement is a
 * direct call, so sizing is still exercised; only re-measurement on resize is
 * inert, and jsdom never resizes anything.
 */
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub implements ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}
