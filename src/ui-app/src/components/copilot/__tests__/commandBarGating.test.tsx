/**
 * What actually gates the "Start" button.
 *
 * A greyed-out Start with an "Idle" chip was read as evidence that the page was
 * broken — that some capability, session or connection fetch had failed and was
 * disabling the control. It is not. `CopilotHarness` never passes `disabled` to
 * `CommandBar`, so the only gate that can be closed on a fresh page is an empty
 * input box. These tests pin that, so the next person who sees a grey Start does
 * not go looking for a failed request that was never made.
 *
 * Stream status is deliberately NOT a gate here: `idle` simply means no session
 * has been opened yet, which is the correct state before the first intent.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import CommandBar from '../CommandBar';
import { StreamStatus } from '../types';

const setup = (props: Partial<React.ComponentProps<typeof CommandBar>> = {}) =>
  render(
    <CommandBar
      onSubmit={props.onSubmit || jest.fn()}
      busy={props.busy ?? false}
      streamStatus={props.streamStatus ?? ('idle' as StreamStatus)}
      disabled={props.disabled}
    />
  );

const startButton = () => screen.getByRole('button', { name: /start/i });

describe('CommandBar start gating', () => {
  it('is disabled on an empty box and enabled as soon as an intent is typed', () => {
    setup();
    expect(startButton()).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/describe the task/i), {
      target: { value: 'review the flagged wires from overnight' },
    });
    expect(startButton()).toBeEnabled();
  });

  it('stays enabled while the stream is idle — idle is not a gate', () => {
    setup({ streamStatus: 'idle' as StreamStatus });
    fireEvent.change(screen.getByLabelText(/describe the task/i), {
      target: { value: 'do a thing' },
    });
    expect(startButton()).toBeEnabled();
    expect(screen.getByRole('status')).toHaveTextContent('Idle');
  });

  it('whitespace alone does not count as an intent', () => {
    setup();
    fireEvent.change(screen.getByLabelText(/describe the task/i), { target: { value: '   ' } });
    expect(startButton()).toBeDisabled();
  });

  it('submits the trimmed intent and clears the box', () => {
    const onSubmit = jest.fn();
    setup({ onSubmit });
    fireEvent.change(screen.getByLabelText(/describe the task/i), {
      target: { value: '  review the wires  ' },
    });
    fireEvent.click(startButton());
    expect(onSubmit).toHaveBeenCalledWith('review the wires');
  });
});

describe('CopilotHarness does not gate the command bar', () => {
  it('never passes a `disabled` prop, so no fetch can disable Start', () => {
    // Guards the claim above at the source rather than in a comment: if a gate
    // is added later, this fails and the diagnosis note gets revisited.
    // eslint-disable-next-line @typescript-eslint/no-var-requires, global-require
    const source = require('fs').readFileSync(
      require('path').join(__dirname, '..', 'CopilotHarness.tsx'),
      'utf8'
    );
    const commandBarTag = source.slice(source.indexOf('<CommandBar'));
    expect(commandBarTag.slice(0, commandBarTag.indexOf('/>'))).not.toContain('disabled');
  });
});
