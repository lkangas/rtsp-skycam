"""Peak-hold ("lighten") stacking kernel.

Adapted from pnuu/sky-cam-cv, function ``_update_max_stack_numba`` in
``bin/sky-cam-cv.py`` at pinned commit
1ca88282b33a6e6ac9163c5812bfd8b2c7393774 (see the ``upstream/`` submodule).
Original author: Panu Lahtinen (pnuu).

For each pixel it keeps the frame whose summed RGB brightness is the highest
seen so far in the current stack — so meteors, aurora and any transient bright
feature accumulate into a single image over the stacking window.

Behaviour is identical to upstream, but the per-channel brightness sum is fused
into the pixel loop instead of a separate ``np.sum(frame, axis=-1)`` pass — that
avoids a full 4 MP allocation + read per frame and is ~3x faster. The op is
memory-bandwidth bound, so it wants very few threads: ``NUMBA_NUM_THREADS=1``
already sustains far above typical stream rates; more run slower *and* hotter.
"""

import numpy as np
from numba import njit, prange


@njit(parallel=True, cache=True)
def update_max_stack(max_stack, frame, stack_sum):
    """In-place peak-hold update.

    Parameters
    ----------
    max_stack : (H, W, 3) uint8   running brightest frame, modified in place
    frame     : (H, W, 3) uint8   new frame to merge in
    stack_sum : (H, W)    uint16  running per-pixel brightness, modified in place
    """
    y, x, _ = frame.shape
    for i in prange(x):
        for j in range(y):
            s = (
                np.uint16(frame[j, i, 0])
                + np.uint16(frame[j, i, 1])
                + np.uint16(frame[j, i, 2])
            )
            if s > stack_sum[j, i]:
                max_stack[j, i, 0] = frame[j, i, 0]
                max_stack[j, i, 1] = frame[j, i, 1]
                max_stack[j, i, 2] = frame[j, i, 2]
                stack_sum[j, i] = s
