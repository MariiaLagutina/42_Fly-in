# Airlines playback lifecycle

The dispatch center replays recorded simulation events. It returns control
without exiting Python. CLI process exit remains in the existing executable
entry points; the default CLI viewer still holds its final frame until close.

```python
run_pygame_airlines(
    visualizer,
    view=None,
    *,
    return_on_completion=False,
    screen=None,
    rng=None,
) -> PlaybackExit
```

`PlaybackExit.CLOSED` reports a window close request. With
`return_on_completion=True`, `PlaybackExit.COMPLETED` reports that the final
replay frame was drawn and presented. It does not report successful vehicle
delivery: simulation outcomes remain separate. A close event takes priority
in that iteration and prevents further updates or drawing.

Without `screen`, the call owns Pygame exclusively. It initializes display
and font subsystems, creates the existing 1350 × 800 display and caption,
and shuts Pygame down on return or failure, including construction failure.
Do not use this mode while another component owns Pygame resources.

With `screen`, the caller supplies the current 1350 × 800 software display
surface and initializes both display and font subsystems beforehand. An
ordinary offscreen surface, another size, or an OpenGL display is rejected.
Airlines does not initialize, replace, rename or destroy the caller's
display, even on close or failure. The caller suspends its event loop for
playback, then redraws its menu or decides to exit the application. Only
one foreground display/event loop is supported.

`AirlinesWindow(visualizer, view=None, *, screen=None, rng=None)` supports
the same ownership modes. Its `run_loop(*, return_on_completion=False)`
returns the same result and performs standalone cleanup. Code constructing
a window solely to draw captures must clean up its standalone Pygame
resources itself, as the capture script does in `finally`.

Create a fresh window and collector for every new simulation, using that
simulation's graph and events. Do not reuse a closed standalone window.
Flight numbers use an instance-local `random.Random`; passing a generator
allows deterministic labels without changing global random state. Capture
tooling passes seed 0 to preserve the existing screenshots and GIF frames.

Lifecycle tests use SDL dummy video/audio, controlled ticks and finite event
batches. Native close-button, focus and menu transitions still need a real
display smoke test when the application is connected in a later milestone.
