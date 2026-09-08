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
