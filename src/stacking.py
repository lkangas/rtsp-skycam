"""Peak-hold ("lighten") stacking kernel.

Adapted verbatim from pnuu/sky-cam-cv, function ``_update_max_stack_numba`` in
``bin/sky-cam-cv.py`` at pinned commit
1ca88282b33a6e6ac9163c5812bfd8b2c7393774 (see the ``upstream/`` submodule).
Original author: Panu Lahtinen (pnuu). Only the public name is changed.

For each pixel it keeps the frame whose summed RGB brightness is the highest
seen so far in the current stack — so meteors, aurora and any transient bright
feature accumulate into a single image over the stacking window.
"""

import numpy as np
from numba import njit, prange


# cache=True persists the JIT-compiled kernel to NUMBA_CACHE_DIR so container
# restarts skip recompilation (the one behavioural change from upstream).
@njit(parallel=True, cache=True)
def update_max_stack(max_stack, frame, stack_sum):
    """In-place peak-hold update.

    Parameters
    ----------
    max_stack : (H, W, 3) uint8   running brightest frame, modified in place
    frame     : (H, W, 3) uint8   new frame to merge in
    stack_sum : (H, W)    uint16  running per-pixel brightness, modified in place
    """
    frame_sum = np.sum(frame, axis=-1, dtype=np.uint16)
    y, x = frame_sum.shape
    for i in prange(x):
        for j in range(y):
            if frame_sum[j, i] > stack_sum[j, i]:
                max_stack[j, i, :] = frame[j, i, :]
                stack_sum[j, i] = frame_sum[j, i]
