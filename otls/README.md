# hpaint changelog 1.1

- Changed eraser group handling from `stroke_#_#` to `__hstroke_#_#`
- Added `Action By Group` parameter, for use with stroke buffer operations. Uses unix pattern matching with Houdini groups. Can be toggled by pressing `a`
- Added safe undo blocks for stroke operations
- Added `Anim Settings` tab for handling nearest-frame display. Includes methods for displaying the last frame, next frame, and ghosting the geometry if the underlying frame is not the editable file.
