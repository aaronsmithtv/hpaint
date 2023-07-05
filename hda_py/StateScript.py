"""
State:          Hpaint 1.3
State type:     aaron_smith::hpaint::1.3
Description:    Viewer state for Hpaint
Author:         Aaron Smith
Date Created:   August 26, 2021 - 11:32:36
"""

import hou
import viewerstate.utils as vsu
import parmutils

import logging
from typing import Any

logging.basicConfig(level=logging.DEBUG)

"""
Thank you for downloading this HDA and spreading the joy of drawing in Houdini.
Hpaint was lovingly made in my free time, if you have any questions please email
me at aaron@aaronsmith.tv, or consider taking a look at the rest of my work at
https://aaronsmith.tv. 

For future updates: https://github.com/aaronsmithtv/hpaint
"""

HDA_VERSION = 1.3
HDA_AUTHOR = "aaronsmith.tv"

GEO_INTERSECTION_TYPE = 4  # The number of the parameter reference to intersection type 'Geometry'

INPUT_GEO_NAME = "INPUT_GEO"
STROKE_READIN_NAME = "STROKE_READIN"


class StrokeParams(object):
    """Stroke instance parameters.

    The class holds the stroke instance parameters as attributes for a given
    stroke operator and instance number.

    Parameters can be accessed as follows:

    params = StrokeParams(node, 55)
    params.colorr.set(red)
    params.colorg.set(green)
    etc...

    Attributes:
        inst: int
            The current stroke parm instance number for the internal stroke SOP.
            Initialized at 1 for each stroke.
            It is unlikely that this number will go above 1, as the stroke SOP is reset
            every time a stroke is drawn and completed.
    """

    def __init__(self, node: hou.Node, inst: int):
        self.inst = inst
        # log_stroke_event(f"StrokeParams `inst` initialized: `{inst}`")

        param_name = 'stroke' + str(inst)
        prefix_len = len(param_name) + 1

        def valid_parm(vparm):
            return vparm.isMultiParmInstance() and vparm.name().startswith(param_name)

        params = filter(valid_parm, node.parms())
        for p in params:
            self.__dict__[p.name()[prefix_len:]] = p
            # log_stroke_event(self.__dict__)


class StrokeData(object):
    """Holds the stroke data.

    Store the stroke's data within class to recall attributes that vary/change across a stroke

    Attributes that do not change across the length of a stroke are stored as metadata.

    Attributes:
        pos: hou.Vector3
        dir: hou.Vector3
        proj_pos: hou.Vector3
        proj_uv: hou.Vector3
        proj_prim: int
        hit: bool
        pressure: float
        time: float
        tilt: float
        angle: float
        roll: float
    """
    VERSION = 2

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @staticmethod
    def create():
        return StrokeData(
            pos=hou.Vector3(0.0, 0.0, 0.0),
            dir=hou.Vector3(0.0, 0.0, 0.0),
            proj_pos=hou.Vector3(0.0, 0.0, 0.0),
            proj_uv=hou.Vector3(0.0, 0.0, 0.0),
            proj_prim=-1,
            hit=0,
            pressure=1.0,
            time=0.0,
            tilt=0.0,
            angle=0.0,
            roll=0.0,
        )

    def reset(self):
        self.pos = hou.Vector3(0.0, 0.0, 0.0)
        self.dir = hou.Vector3(0.0, 0.0, 0.0)
        self.hit = 0
        self.proj_pos = hou.Vector3(0.0, 0.0, 0.0)
        self.proj_uv = hou.Vector3(0.0, 0.0, 0.0)
        self.proj_prim = -1
        self.pressure = 1.0
        self.time = 0.0
        self.tilt = 0.0
        self.angle = 0.0
        self.roll = 0.0

    def encode(self):
        """Convert the data members to a hex string
        """
        stream = vsu.ByteStream()
        stream.add(self.pos, hou.Vector3)
        stream.add(self.dir, hou.Vector3)
        stream.add(self.pressure, float)
        stream.add(self.time, float)
        stream.add(self.tilt, float)
        stream.add(self.angle, float)
        stream.add(self.roll, float)
        stream.add(self.proj_pos, hou.Vector3)
        stream.add(self.proj_prim, int)
        stream.add(self.proj_uv, hou.Vector3)
        stream.add(self.hit, int)
        return stream

    def decode(self, stream):
        pass


class StrokeMetaData(object):
    """Holds the meta data from the stroke state client node.

    These are translated into primitive attributes by the Stroke SOP.
    The default behaviour if this state is to copy any stroke_ prefixed
    parameters into this meta data, but the build_stroke_metadata can
    be overridden to add additional information.
    """

    def __init__(self):
        self.name = None
        self.size = 0
        self.type = None
        self.value = None

    @staticmethod
    def create(meta_data_array):
        """Creates an array of StrokeMetaData from the client node parameters and converts it to a json string
        """
        import json

        # insert number of total elements
        meta_data_array.insert(0, len(meta_data_array))

        if len(meta_data_array) == 1:
            meta_data_array.append({})

        return json.dumps(meta_data_array)

    @staticmethod
    def build_parms(node):
        """Returns an array of stroke parameters to consider for meta data
        """

        def filter_tparm(t):
            """
                        Filter out template parameters
                        """
            prefix = 'stroke_'
            builtins = (
                'stroke_numstrokes',
                'stroke_radius',
                'stroke_opacity',
                'stroke_tool',
                'stroke_color',
                'stroke_projtype',
                'stroke_projcenter',
                'stroke_projgeoinput',
            )
            # Take all parms which start with 'stroke_' but are not builtin
            return t.name().startswith(prefix) and t.name() not in builtins

        g = node.parmTemplateGroup()
        return filter(filter_tparm, parmutils.getAllParmTemplates(g))


def project_point_dir(
        node: hou.Node,
        mouse_point: hou.Vector3,
        mouse_dir: hou.Vector3,
        intersect_geometry: hou.Geometry,
        plane_center: hou.Vector3 = None) -> (hou.Vector3, hou.Vector3, hou.Vector3, int, bool):
    """Performs a geometry intersection and returns a tuple with the intersection info.

    Returns:
        point: intersection position
        normal: intersected geometry's normal
        uvw: parametric UV coordinates
        prim_num: intersection primitive number
        hit_success: return True if operation is successful or False otherwise
    """
    proj_type = _eval_param(node, "stroke_projtype", 0)
    prim_num = -1
    uvw = hou.Vector3(0.0, 0.0, 0.0)

    if proj_type == GEO_INTERSECTION_TYPE and intersect_geometry is not None:
        hit_point_geo = hou.Vector3()
        normal = hou.Vector3()

        prim_num = intersect_geometry.intersect(mouse_point, mouse_dir, hit_point_geo, normal, uvw, None, 0,
                                                1e18, 5e-3)
        if prim_num >= 0:
            # log_stroke_event(f"Projected from point `{mouse_point}` in dir `{mouse_dir}` with `{intersect_geometry}`, returned data: Geo: `{hit_point_geo}`, Normal: `{normal}`, UVW: `{uvw}`, `{prim_num}`")
            return hit_point_geo, normal, uvw, prim_num, True

    if plane_center is None:
        plane_center = _eval_param_v3(node, "stroke_projcenterx", "stroke_projcentery", "stroke_projcenterz", (0, 0, 0))
        plane_dir = _projection_dir(proj_type, mouse_dir)
    else:
        plane_dir = mouse_dir * -1

    try:
        hit_point_plane = hou.hmath.intersectPlane(plane_center, plane_dir, mouse_point, mouse_dir)
        # log_stroke_event(f"Intersected position: `{hit_point_plane}`, from plane point: `{plane_center}`, plane normal: `{plane_dir}`, ray origin: `{mouse_point}`, ray dir: `{mouse_dir}`")
    except Exception:
        hit_point_plane = hou.Vector3()

    return hit_point_plane, None, uvw, prim_num, False


class StrokeCursorAdv(object):
    """Implements the brush cursor used by the stroke state.

    Handles the creation of the advanced drawable, and provides methods
    for various transform operations.

    Use self.drawable to edit drawable parameters such as the colour, and glow width.
    """

    def __init__(self, scene_viewer: hou.SceneViewer, state_name: hou.SceneViewer):
        self.mouse_xform = hou.Matrix4()

        self.scene_viewer = scene_viewer
        log_stroke_event(f"Scene Viewer assigned: `{self.scene_viewer}`")
        self.state_name = state_name
        log_stroke_event(f"State Name assigned: `{self.scene_viewer}`")

        # initialise the advanced drawable
        self.drawable = self.init_brush()

        # return whether the cursor is intersecting with geometry for geo masking operations
        self.is_hit = False
        #  return the hit primitive for eraser-based operations
        self.hit_prim = -1

        # initialise the location in geometry space
        self.xform = hou.Matrix4(0.05)

        # initialise the mapping from 'geometry space' to 'model space'
        self.model_xform = hou.Matrix4(1)

        # record the last position for model translation
        self.last_cursor_pos = hou.Vector3()

        # display prompt when entering the viewer state
        self.prompt = "Left click to draw strokes. Ctrl+Left to erase strokes, Ctrl+Shift+Left to delete strokes. Shift drag to change stroke size."

        # control for whether drawing should be disabled (to allow resizing operation)
        self.resizing = False

    def init_brush(self):
        """Create the advanced drawable and return it to self.drawable
        """
        sops = hou.sopNodeTypeCategory()
        verb = sops.nodeVerb('sphere')

        verb.setParms(
            {
                "type": 2,
                "orient": 1,
                "rows": 13,
                "cols": 24
            },
        )
        cursor_geo = hou.Geometry()
        verb.execute(cursor_geo, [])

        cursor_draw = hou.GeometryDrawableGroup("cursor")

        # adds the drawables
        cursor_draw.addDrawable(
            hou.GeometryDrawable(
                self.scene_viewer,
                hou.drawableGeometryType.Face, "face",
                params={
                    'color1': (0.0, 1.0, 0.0, 1.0),
                    'color2': (0.0, 0.0, 0.0, 0.33),
                    'highlight_mode': hou.drawableHighlightMode.MatteOverGlow,
                    'glow_width': 2
                }
            )
        )
        cursor_draw.setGeometry(cursor_geo)

        return cursor_draw

    def set_color(self, color: hou.Vector4):
        """Change the colour of the drawable whilst editing parameters in the viewer state
        """
        self.drawable.setParams({'color1': color})

    def show(self):
        """Enable the drawable
        """
        self.drawable.show(True)

    def hide(self):
        """Disable the drawable
        """
        self.drawable.show(False)

    def update_position(
            self,
            node: hou.Node,
            mouse_point: hou.Vector3,
            mouse_dir: hou.Vector3,
            rad: float,
            intersect_geometry: hou.Geometry) -> None:
        """Overwrites the model transform with an intersection of cursor to geo.
        also records if the intersection is hitting geo, and which prim is recorded in the hit
        """
        (cursor_pos, normal, uvw, prim_num, hit) = project_point_dir(node, mouse_point, mouse_dir, intersect_geometry)

        # update self.is_hit for geo masking
        self.is_hit = hit
        self.hit_prim = prim_num

        self.last_cursor_pos = cursor_pos

        # Position is at the intersection point oriented to go along the normal
        srt = {
            'translate': (self.last_cursor_pos[0], self.last_cursor_pos[1], self.last_cursor_pos[2]),
            'scale': (rad, rad, rad),
            'rotate': (0, 0, 0),
        }

        rotate_quaternion = hou.Quaternion()

        if hit and normal is not None:
            rotate_quaternion.setToVectors(hou.Vector3(0, 0, 1), normal)
        else:
            rotate_quaternion.setToVectors(hou.Vector3(0, 0, 1), hou.Vector3(mouse_dir).normalized())

        rotate = rotate_quaternion.extractEulerRotates()
        srt['rotate'] = rotate

        self.update_xform(srt)

    def update_xform(self, srt: dict) -> None:
        """Overrides the current transform with the given dictionary.
        The entries should match the keys of hou.Matrix4.explode.
        """
        try:
            current_srt = self.xform.explode()
            current_srt.update(srt)
            self.xform = hou.hmath.buildTransform(current_srt)
            self.drawable.setTransform(self.xform * self.model_xform)
        except hou.OperationFailed:
            return

    def update_model_xform(self, viewport: hou.GeometryViewport) -> None:
        """Update attribute model_xform by the selected viewport.
        This will vary depending on our position type.
        """

        self.model_xform = viewport.modelToGeometryTransform().inverted()
        self.mouse_xform = hou.Matrix4(1.0)

    def render(self, handle: int) -> None:
        """Renders the cursor in the viewport with the onDraw python state

        optimise the onDraw method by reducing the amount of operations
        calculated at draw time as possible

        Parameters:
            handle: int
                The current integer handle number
        """

        self.drawable.draw(handle)

    def show_prompt(self) -> None:
        """Write the tool prompt used in the viewer state
        """
        self.scene_viewer.setPromptMessage(self.prompt)


def _eval_param(node: hou.Node, parm_path: str, default: Any) -> Any:
    """ Evaluates param on node, if it doesn't exist return default.
    """
    try:
        return node.evalParm(parm_path)
    except Exception:
        return default


def _eval_param_v3(node: hou.Node, param1: str, param2: str, param3: str, default: Any) -> Any:
    """Evaluates vector3 param on node, if it doesn't exist return default.
    """
    try:
        return hou.Vector3(
            node.evalParm(param1), node.evalParm(param2), node.evalParm(param3))
    except Exception:
        return hou.Vector3(default)


def _eval_param_c(node: hou.Node, param1: str, param2: str, param3: str, default: Any) -> Any:
    """Evaluates color param on node, if it doesn't exist return default.
    """
    try:
        return hou.Color(
            node.evalParm(param1), node.evalParm(param2), node.evalParm(param3))
    except Exception:
        return hou.Color(default)


def _projection_dir(proj_type: int, screen_space_projection_dir: hou.Vector3) -> hou.Vector3:
    """Convert the projection menu item into a geometry projection direction.
    """
    if proj_type == 0:
        return hou.Vector3(0, 0, 1)
    elif proj_type == 1:
        return hou.Vector3(1, 0, 0)
    elif proj_type == 2:
        return hou.Vector3(0, 1, 0)
    else:
        return screen_space_projection_dir


def get_node_stroke_colour(node: hou.Node) -> (float, float, float, float):
    cursor_cr = node.parm('hp_colourr').eval()
    cursor_cg = node.parm('hp_colourg').eval()
    cursor_cb = node.parm('hp_colourb').eval()
    cursor_ca = node.parm('hp_coloura').eval()
    return cursor_ca, cursor_cb, cursor_cg, cursor_cr


class State(object):
    """Stroke state implementation to handle the mouse/tablet interaction.

    Attributes:
        state_name: str
            The name of the HDA, for example, `aaron_smith::test::hpaint::1.2`
        scene_viewer: hou.SceneViewer
            The current scene viewer pane tab interacted with
    """

    RESIZE_ACCURATE_MODE = 0.2

    def __init__(self, state_name: str, scene_viewer: hou.SceneViewer):
        self.__dict__.update(kwargs)

        # log_stroke_event(f"Initialized statename: `{state_name}`, scene viewer: `{scene_viewer}`")

        self.state_name = state_name
        self.scene_viewer = scene_viewer

        self.strokes = []
        self.strokes_mirror_data = []
        self.strokes_next_to_encode = 0
        self.mouse_point = hou.Vector3()
        self.mouse_dir = hou.Vector3()
        self.stopwatch = vsu.Stopwatch()
        self.epoch_time = 0

        # meta_data_params is a cache for which parameters to copy
        # to the metadata.
        self.meta_data_parms = None

        self.enable_shift_drag_resize = True

        # capture_parms are any extra keys that should be passed from
        # the kwargs of the event callbacks to the stroke-specific
        # event callbacks.
        self.capture_parms = []

        # stores the geometry to intersect with. in hpaint, this is whatever is
        # cooked at the null 'INPUT_GEO' (to swap between grid or input)
        self.intersect_geometry = None

        # create the interactive cursor, which is represented in the viewport
        # as a drawable. Storing it to allow changes to transform, colour and alpha
        self.cursor_adv = StrokeCursorAdv(self.scene_viewer, self.state_name)

        self.undo_state = 0

        # creates a secondary drawable, which is the title/author text displayed in viewport
        self.text_drawable = hou.TextDrawable(self.scene_viewer, 'text_drawable_name')
        self.text_drawable.show(True)

        # decide if geo masking is used - this is permanently enabled
        self.geo_mask = False

        # reorganised method for masking strokes to geometry for optimisation
        # record the first hit to begin an undo state as well as beginning a
        # stroke input that can be continued in the viewer state while LMB is held down
        self.first_hit = True

        # used to decide whether the eraser should partially erase strokes or
        # if it should delete an entire stroke instead.
        self.eraser_fullstroke = False

        # controls if the eraser is used, this also changes the cursor colour
        # to red if true
        self.eraser_enabled = False

        self.last_mouse_x = 0
        self.last_mouse_y = 0

        self.last_drawable_colour = hou.Vector4(0.05, 0.05, 0.05, 1.0)

        self.last_intersection_pos = None

        self.pressure_enabled = True

        self.radius_parm_name = 'stroke_radius'
        self.strokecache_parm_name = 'hp_strokecache'
        self.strokenum_parm_name = 'hp_stroke_num'
        # text draw generation
        self.text_params = self.generate_text_drawable(self.scene_viewer)

    def onPreStroke(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called when a stroke is started.
        Override this to setup any stroke_ parameters.
        """
        vsu.triggerParmCallback("prestroke", node, ui_event.device())

    def onPostStroke(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called when a stroke is complete
        Appended to any end block in stroke_interactive and masked equivalent
        """

        # +1 to the HDA's internal stroke counter. used to generate
        # unique stroke IDs that the eraser can read
        self.add_stroke_num(node)

        # now that a stroke is completed, store it in the 'stroke buffer'
        # which is a data parm that contains all currently drawn geometry
        # this is for speeding the viewer state up while drawing
        self.cache_strokes(node)

        # revert the stroke SOP to an initialised state to begin a fresh stroke
        self.reset_stroke_parms(node)

        vsu.triggerParmCallback("poststroke", node, ui_event.device())

    def onPreApplyStroke(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called before new stroke values are copied.
        This is done during the stroke operation.

        Override this to do any preparation just before the stroke
        parameters are updated for an active stroke.
        """
        pass

    def onPostApplyStroke(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called before after new stroke values are copied. This is done
        during the stroke operation.

        Override this to do any clean up for every stroke
        update. This can be used to break up a single stroke
        into a series of operations, for example.
        """
        pass

    def onPreMouseEvent(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called at the start of every mouse event.

        This is outside of undo blocks, so do not
        set parameters without handling undos.

        Override this to inject code just before all mouse event
        processing
        """
        pass

    def onPostMouseEvent(self, node: hou.Node, ui_event: hou.UIEvent) -> None:
        """Called at the end of every mouse event.

        This is outside of undo blocks, so do not
        set parameters without handling undos.

        Override this to inject code just after all mouse event
        processing
        """
        pass

    def build_stroke_metadata(self, node: hou.Node) -> list:
        """Returns an array of dictionaries storing the metadata for the stroke.

        This is encoded as JSON and put in the stroke metadata parameter.

        Base behaviour is to encode all stroke_ prefixed parms.

        mirrorxform is the current mirroring transform being
        written out.

        Override this to add metadata without the need to
        make stroke_ parameters.
        """
        convertible_to_int = (
            hou.parmTemplateType.Toggle,
            hou.parmTemplateType.Menu,
        )

        meta_data_array = []
        for p in self.meta_data_parms:
            name = p.name()
            data_type = p.type()

            meta_data = StrokeMetaData()
            meta_data.size = 1
            meta_data.name = name

            if data_type == hou.parmTemplateType.Float:
                values = node.evalParmTuple(name)
                meta_data.type = "float"
                meta_data.size = len(values)
                meta_data.value = " ".join(map(str, values))
            elif data_type == hou.parmTemplateType.Int:
                values = node.evalParmTuple(name)
                meta_data.type = "int"
                meta_data.size = len(values)
                meta_data.value = " ".join(map(str, values))
            elif data_type == hou.parmTemplateType.String:
                meta_data.type = "string"
                meta_data.value = node.evalParm(name)
            elif data_type in convertible_to_int:
                meta_data.type = "int"
                meta_data.value = str(node.evalParm(name))
            else:
                continue

            meta_data_array.append(meta_data.__dict__)
        return meta_data_array

    def onEnter(self, kwargs: dict) -> None:
        """Called whenever the state begins.

        Override this to perform any setup, such as visualizers,
        that should be active whenever the state is.

        Parameters:
            kwargs: dict
                The keyword arguments for the viewer state beginning. These kwargs
                are generated by houdini in the following format:
                'state_name', 'state_parms', 'state_flags' ('mouse_drag', 'redraw'), 'node'
        """

        # log_stroke_event(f"onEnter kwargs: `{kwargs}`")

        node = kwargs['node']

        # replaced STROKECURSOR.size with float value
        # initialise the cursor radius
        rad = _eval_param(node, self.get_radius_parm_name(), 0.05)
        self.cursor_adv.update_xform({'scale': (rad, rad, rad)})
        # hide the cursor before it has inherited a screen transform
        self.cursor_adv.hide()

        # pre-build a list of meta data parameters from the node
        self.meta_data_parms = StrokeMetaData.build_parms(node)

        # display the viewer state prompt
        self.cursor_adv.show_prompt()

    def onExit(self, kwargs: dict) -> None:
        """Called whenever the state ends.

        Override this to perform any cleanup, such as visualizers,
        that should be finished whenever the state is.
        """
        vsu.Menu.clear()

    def onMouseEvent(self, kwargs: dict) -> None:
        """Process mouse events, such as a left or right mouse button press

        Button press events can be evaluated using the `ui_event` kwarg, in a
        method such as `ui_event.device().isLeftButton()`

        Parameters:
            kwargs: dictViewerEvent
                The keyword arguments for the mouse moving during viewer state event.
                These kwargs are generated by houdini in the following format:
                'state_name', 'state_parms', 'state_flags' ('mouse_drag', 'redraw'),
                'ui_event' (of class ViewerEvent. This contains information on the device (keys) pressed, pressure, tilt etc.),
                'node'
        """

        # log_stroke_event(f"Kwargs for onMouseEvent: `{kwargs}`")

        ui_event: hou.ViewerEvent = kwargs['ui_event']
        node: hou.Node = kwargs['node']

        self.transform_cursor_position(node, ui_event)

        # display the cursor after xform applied
        self.cursor_adv.show()

        # Ignore commands if mousewheel is currently moving
        if self.eval_mousewheel_movement(ui_event):
            return

        # SHIFT DRAG RESIZING
        started_resizing = False
        started_resizing = self.shift_key_resize_event(started_resizing, ui_event)

        if self.cursor_adv.resizing:
            self.resize_by_ui_event(node, started_resizing, ui_event)
            return

        # update the state of eraser usage
        self.update_eraser(ui_event)

        self.apply_drawable_brush_colour(node)

        self.handle_stroke_event(ui_event, node)

        # Geometry masking system
        # If the cursor moves off of the geometry during a stroke draw - a new stroke is created.
        # New strokes cannot be created off draw
        if not self.eraser_enabled:
            self.eval_mask_state(node)
            if self.geo_mask:
                self.stroke_interactive_mask(ui_event, node)
                return
            # If geometry masking is disabled, hits are not accounted for
            # Using a simplified version of the sidefx_stroke.py method
            else:
                self.stroke_interactive(ui_event, node)
                return
        else:
            self.eraser_interactive(ui_event, node)
            return

    def eval_mousewheel_movement(self, ui_event: hou.UIEvent) -> bool:
        mw = ui_event.device().mouseWheel()

        if 1.0 >= mw >= -1.0:
            return True
        return False

    def eval_mask_state(self, node: hou.Node):
        mask_state_parm = node.parm("disable_geo_mask")
        mask_state = mask_state_parm.evalAsInt()
        if mask_state == 1:
            if self.geo_mask:
                self.geo_mask = False
        else:
            if not self.geo_mask:
                self.geo_mask = True

    def apply_drawable_brush_colour(self, node: hou.Node):
        if not self.eraser_enabled:
            cursor_ca, cursor_cb, cursor_cg, cursor_cr = get_node_stroke_colour(node)

            cursor_color = hou.Vector4(cursor_cr, cursor_cg, cursor_cb, cursor_ca)

            self.cursor_adv.set_color(cursor_color)
        else:
            # set eraser colour
            self.cursor_adv.set_color(hou.Vector4(1.0, 0.0, 0.0, 1.0))

    def resize_by_ui_event(self, node: hou.Node, started_resizing: bool, ui_event: hou.ViewerEvent) -> None:
        """Given a UI event and condition for resizing, resize the cursor with the current parameter size.
        """
        mouse_x = ui_event.device().mouseX()
        mouse_y = ui_event.device().mouseY()
        # using the cached mouse pos, add the current mouse pos
        # to the old pos to get a distance (used as new radius multiplier)
        dist = -self.last_mouse_x + mouse_x
        dist += -self.last_mouse_y + mouse_y
        self.last_mouse_x = mouse_x
        self.last_mouse_y = mouse_y
        if started_resizing:
            # opens an undo block for the brush operation
            self.undoblock_open('Brush Resize')
            pass
        self.resize_cursor(node, dist)
        if ui_event.reason() == hou.uiEventReason.Changed:
            # closes the current brush undo block
            self.cursor_adv.resizing = False
            self.undoblock_close()

    def shift_key_resize_event(self, started_resizing: bool, ui_event: hou.ViewerEvent) -> bool:
        """Enables static shift-key resizing (similar to photoshop)
        """
        # check shift (resize key) is not conflicting with eraser keys
        if ui_event.reason() == hou.uiEventReason.Start and ui_event.device().isShiftKey() and not ui_event.device().isCtrlKey():
            # if stroke has begun, enable resizing and cache mouse position
            self.cursor_adv.resizing = True
            started_resizing = True
            self.last_mouse_x = ui_event.device().mouseX()
            self.last_mouse_y = ui_event.device().mouseY()
        return started_resizing

    def transform_cursor_position(self, node: hou.Node, ui_event: hou.ViewerEvent) -> None:
        """Transforms the cursor position to the new rayed viewer event position

        THis uses the position of the mouse point and relative direction towards
        the 3D scene to figure out where on the geometry the cursor should be displayed.
        """
        # record a mouse position + direction from the ui_event
        (self.mouse_point, self.mouse_dir) = ui_event.ray()
        # logic for applying tablet pressure to cursor radius, and
        # updating the cursor transform in 3d space
        # check if there are no device events in the queue
        if not ui_event.hasQueuedEvents() and not self.cursor_adv.resizing:
            # evaluate the radius parameter for a 'default' radius value
            radius_parmval = _eval_param(node, self.get_radius_parm_name(), 0.05)
            if ui_event.device().isLeftButton() and len(self.strokes) > 0:
                if self.is_pressure_enabled():
                    # if a stroke currently exists, update the default radius value
                    # with a multiplication of the current tablet pressure
                    pressure_rad = self.strokes[-1].pressure
                    radius_parmval *= pressure_rad

            self.cursor_adv.update_model_xform(ui_event.curViewport())
            self.cursor_adv.update_position(
                node,
                mouse_point=self.mouse_point,
                mouse_dir=self.mouse_dir, rad=radius_parmval,
                intersect_geometry=self.get_intersection_geometry(node)
            )

    def onMouseWheelEvent(self, kwargs: dict) -> None:
        """Called whenever the mouse wheel moves.

        Default behaviour is to resize the cursor.

        Override this to do different things on mouse wheel.

        This contains the standard onMouseWheelEvent kwargs specified in the
        Houdini viewer state documentation.
        """
        ui_event = kwargs['ui_event']
        node = kwargs['node']

        dist = ui_event.device().mouseWheel()
        dist *= 10.0

        # Slow resizing enabled on shift key
        if ui_event.device().isShiftKey() is True:
            dist *= State.RESIZE_ACCURATE_MODE

        # middle mouse event refreshes the parm enough times to create
        # unnecessary undo spam - this disables resize_cursor undos
        with hou.undos.disabler():
            self.resize_cursor(node, dist)

    def onResume(self, kwargs: dict) -> None:
        """Called whenever the state is resumed from an interruption.

        This contains the standard onResume kwargs specified in the
        Houdini viewer state documentation.
        """
        self.cursor_adv.show()
        self.cursor_adv.show_prompt()

        self.log('cursor = ', self.cursor_adv)

    def onInterrupt(self, kwargs: dict) -> None:
        """Called whenever the state is temporarily interrupted.

        This contains the standard onInterrupt kwargs specified in the
        Houdini viewer state documentation.
        """
        self.cursor_adv.hide()

    def onMenuAction(self, kwargs: dict) -> None:
        """Called when a state menu is selected.

        This contains the standard onMenuAction kwargs specified in the
        Houdini viewer state documentation.
        """
        menu_item = kwargs['menu_item']
        node = kwargs['node']

        if menu_item == 'press_save_to_file':
            node.parm('hp_save_file').pressButton()

        elif menu_item == 'press_clear_buffer':
            node.parm('hp_clear_buffer').pressButton()

        elif menu_item == 'toggle_guide_vis':
            guide_vis_parm = node.parm('hp_hide_geo')
            guide_vis_tog = guide_vis_parm.evalAsInt()
            if guide_vis_tog:
                guide_vis_parm.set(0)
            else:
                guide_vis_parm.set(1)

        elif menu_item == 'toggle_screen_draw':
            screen_draw_parm = node.parm('hp_sd_enable')
            screen_draw_tog = screen_draw_parm.evalAsInt()
            if screen_draw_tog:
                screen_draw_parm.set(0)
            else:
                screen_draw_parm.set(1)

        elif menu_item == 'stroke_sdshift_down':
            self.shift_surface_dist(node, 0)

        elif menu_item == 'stroke_sdshift_up':
            self.shift_surface_dist(node, 1)

        elif menu_item == 'action_by_group':
            actiongroup_parm = node.parm('hp_grp_iso')
            actiongroup_tog = actiongroup_parm.evalAsInt()
            if actiongroup_tog:
                actiongroup_parm.set(0)
            else:
                actiongroup_parm.set(1)

    def onDraw(self, kwargs: dict) -> None:
        """Called every time the viewport renders.

        This contains the standard onDraw kwargs specified in the
        Houdini viewer state documentation.
        """

        # draw the text in the viewport upper left
        handle = kwargs['draw_handle']

        self.text_drawable.draw(handle, self.text_params)

        # draw the cursor
        self.cursor_adv.render(handle)

    def get_radius_parm_name(self) -> str:
        """Returns the parameter name for determining the current radius of the brush.
        """
        return self.radius_parm_name

    def get_strokecache_parm_name(self) -> str:
        """Returns the name of the hpaint strokecache
        """
        return self.strokecache_parm_name

    def get_strokenum_parm_name(self) -> str:
        """Returns the name of the hpaint strokecache
        """
        return self.strokenum_parm_name

    def get_intersection_geometry(self, node: hou.Node) -> hou.Geometry:
        """Returns the geometry to use for intersections of the ray.
        """
        proj_type = _eval_param(node, "stroke_projtype", 0)

        if proj_type == GEO_INTERSECTION_TYPE:
            if len(node.inputs()) and node.inputs()[0] is not None:
                # check if intersect is being used as eraser or pen
                if not self.eraser_enabled:
                    isectnode = node.node(INPUT_GEO_NAME)
                else:
                    isectnode = node.node(STROKE_READIN_NAME)
                if self.intersect_geometry is None:
                    self.intersect_geometry = isectnode.geometry()
                else:
                    # Check to see if we have already cached this.
                    if self.intersect_geometry.sopNode() != isectnode:
                        self.intersect_geometry = isectnode.geometry()
            else:
                self.intersect_geometry = None
        return self.intersect_geometry

    def active_mirror_transforms(self) -> hou.Matrix4:
        """Returns a list of active transforms to mirror the incoming strokes with.

        The first should be identity to represent passing through.
        If an empty list, no strokes will be recorded.

        Override this to add mirror transforms.
        """
        result = hou.Matrix4()
        result.setToIdentity()
        return [result]

    def handle_stroke_end(self, node: hou.Node, ui_event: hou.ViewerEvent) -> None:
        """Handles the end of a stroke"""
        self.reset_active_stroke()
        self.first_hit = True
        self.onPostStroke(node, ui_event)
        self.undoblock_close()

    def stroke_interactive_mask(self, ui_event: hou.ViewerEvent, node: hou.Node) -> None:
        """The logic for drawing a stroke, opening/closing undo blocks, and assigning prestroke / poststroke callbacks.

        The 'mask' variation of stroke_interactive uses the
        'is hit' attribute of the drawable cursor to close
        strokes that are drawn off the edge of the mask geo.
        """
        is_active_or_start = ui_event.reason() in (hou.uiEventReason.Active, hou.uiEventReason.Start)
        is_changed = ui_event.reason() == hou.uiEventReason.Changed
        is_cursor_hit = self.cursor_adv.is_hit

        if is_active_or_start and self.first_hit and is_cursor_hit:
            self.undoblock_open('Draw Stroke')
            self.reset_active_stroke()
            self.onPreStroke(node, ui_event)
            self.apply_stroke(node, False)
            self.first_hit = False

        elif is_active_or_start and not self.first_hit:
            if is_cursor_hit:
                self.apply_stroke(node, True)
            else:
                self.handle_stroke_end(node, ui_event)

        elif is_changed and not self.first_hit:
            self.handle_stroke_end(node, ui_event)

    def stroke_interactive(self, ui_event: hou.ViewerEvent, node: hou.Node) -> None:
        """The logic for drawing a stroke, opening/closing undo blocks, and assigning prestroke / poststroke callbacks.
        """
        is_active_or_start = ui_event.reason() in (hou.uiEventReason.Active, hou.uiEventReason.Start)
        is_changed = ui_event.reason() == hou.uiEventReason.Changed

        if is_active_or_start and self.first_hit:
            self.undoblock_open('Draw Stroke')
            self.reset_active_stroke()
            self.onPreStroke(node, ui_event)
            self.apply_stroke(node, False)
            self.first_hit = False

        elif is_active_or_start and not self.first_hit:
            self.apply_stroke(node, True)

        elif is_changed and not self.first_hit:
            self.handle_stroke_end(node, ui_event)

    def eraser_interactive(self, ui_event: hou.ViewerEvent, node: hou.Node) -> None:
        """The logic for erasing as a stroke, and opening an eraser-specific undo block.
        """
        if ui_event.reason() == hou.uiEventReason.Active or ui_event.reason() == hou.uiEventReason.Start:
            if self.first_hit is True:
                self.undoblock_open('Eraser')
                self.first_hit = False

            if self.cursor_adv.is_hit and self.cursor_adv.hit_prim >= 0:

                intersect_geometry = self.get_intersection_geometry(node)

                # get the intersecting prim from the cursor, to delete prim seg
                geo_prim = intersect_geometry.prim(self.cursor_adv.hit_prim)

                if geo_prim is not None:
                    seg_id = geo_prim.attribValue("seg_id")
                    stroke_id = geo_prim.attribValue("stroke_id")

                    # segment + stroke groups are assigned to strokes during their SOP
                    # generation process in-HDA. This process finds the geometry
                    # associated with the group name and replaces the stroke buffer
                    # with a version without the associated geo.
                    if self.eraser_fullstroke is False:
                        seg_group_name = "__hstroke_{0}_{1}".format(stroke_id, seg_id)
                    else:
                        seg_group_name = "__hstroke_{0}".format(stroke_id)

                    # load in the stroke buffer geometry
                    stroke_data_parm = node.parm(self.get_strokecache_parm_name())
                    cache_geo = stroke_data_parm.evalAsGeometry()

                    seg_group = cache_geo.findPrimGroup(seg_group_name)

                    if seg_group is not None:
                        seg_group_prims = seg_group.prims()

                        new_geo = hou.Geometry()

                        new_geo.merge(cache_geo)

                        new_geo.deletePrims(seg_group_prims)

                        if new_geo:
                            stroke_data_parm.set(new_geo)

        elif ui_event.reason() == hou.uiEventReason.Changed:
            self.undoblock_close()

            self.first_hit = True

    def resize_cursor(self, node: hou.Node, dist: float) -> None:
        """Adjusts the current stroke radius by a requested bump.

        Used internally.
        """
        scale = pow(1.01, dist)
        stroke_radius = node.parm(self.get_radius_parm_name())

        rad = stroke_radius.evalAsFloat()
        rad *= scale

        stroke_radius.set(rad)
        self.cursor_adv.update_xform({'scale': (rad, rad, rad)})

    def to_hbytes(self, mirror_data) -> bytes:
        """Encodes the list of StrokeData as an array of bytes.

        This byte stream is expected by the stroke SOP's raw data parameter..
        """
        # log_stroke_event(f"Byte stream encoded for mirror data: `{mirror_data}`")

        stream = vsu.ByteStream()
        stream.add(StrokeData.VERSION, int)
        stream.add(len(self.strokes), int)
        stream.add(mirror_data, vsu.ByteStream)
        return stream.data()

    def reset_active_stroke(self):
        self.strokes = []
        self.strokes_mirror_data = []
        self.strokes_next_to_encode = 0

    def apply_stroke(self, node: hou.Node, update: bool) -> None:
        """Updates the stroke multiparameter from the current self.strokes information.

        Parameters:
            node: hou.Node
                The node to evaluate stroke parameters on.
            update: bool
                Bool for if the stroke is being updated, or is starting a new stroke.
        """
        stroke_numstrokes_param = node.parm('stroke_numstrokes')

        # Performs the following as undoable operations
        with hou.undos.group("Draw Stroke"):

            stroke_numstrokes = stroke_numstrokes_param.evalAsInt()
            stroke_radius = _eval_param(node, self.get_radius_parm_name(), 0.05)
            stroke_opacity = _eval_param(node, 'stroke_opacity', 1)
            stroke_tool = _eval_param(node, 'stroke_tool', -1)
            stroke_color = _eval_param_c(
                node,
                'stroke_colorr',
                'stroke_colorg',
                'stroke_colorb',
                (1, 1, 1)
            )
            stroke_projtype = _eval_param(node, 'stroke_projtype', 0)
            stroke_projcenter = _eval_param_v3(
                node,
                'stroke_projcenterx',
                'stroke_projcentery',
                'stroke_projcenterz',
                (0, 0, 0)
            )
            proj_dir = _projection_dir(stroke_projtype, self.mouse_dir)

            mirrorlist = self.active_mirror_transforms()

            if stroke_numstrokes == 0 or not update:
                stroke_numstrokes += len(mirrorlist)

            stroke_numstrokes_param.set(stroke_numstrokes)

            activestroke = stroke_numstrokes - len(mirrorlist) + 1

            if self.strokes_next_to_encode > len(self.strokes):
                self.strokes_next_to_encode = 0
                self.strokes_mirror_data = []

            extra_mirrors = len(mirrorlist) - len(self.strokes_mirror_data)
            if extra_mirrors > 0:
                self.strokes_mirror_data.extend([vsu.ByteStream() for _ in range(extra_mirrors)])

            for (mirror, mirror_data) in zip(mirrorlist, self.strokes_mirror_data):
                meta_data_array = self.build_stroke_metadata(node)
                stroke_meta_data = StrokeMetaData.create(meta_data_array)

                params = StrokeParams(node, activestroke)
                activestroke = activestroke + 1

                # Setting Stroke Params
                params.radius.set(stroke_radius)
                params.opacity.set(stroke_opacity)
                params.tool.set(stroke_tool)
                (r, g, b) = stroke_color.rgb()
                params.colorr.set(r)
                params.colorg.set(g)
                params.colorb.set(b)
                params.projtype.set(stroke_projtype)
                params.projcenterx.set(stroke_projcenter[0])
                params.projcentery.set(stroke_projcenter[1])
                params.projcenterz.set(stroke_projcenter[2])
                params.projdirx.set(proj_dir[0])
                params.projdiry.set(proj_dir[1])
                params.projdirz.set(proj_dir[2])

                mirroredstroke = StrokeData.create()
                for i in range(self.strokes_next_to_encode, len(self.strokes)):
                    stroke = self.strokes[i]
                    mirroredstroke.reset()
                    mirroredstroke.pos = stroke.pos * mirror
                    dir4 = hou.Vector4(stroke.dir)
                    dir4[3] = 0
                    dir4 = dir4 * mirror
                    mirroredstroke.dir = hou.Vector3(dir4)

                    mirroredstroke.proj_pos = hou.Vector3(0.0, 0.0, 0.0),
                    mirroredstroke.proj_uv = hou.Vector3(0.0, 0.0, 0.0),
                    mirroredstroke.proj_prim = -1,
                    mirroredstroke.pressure = stroke.pressure
                    mirroredstroke.time = stroke.time
                    mirroredstroke.tilt = stroke.tilt
                    mirroredstroke.angle = stroke.angle
                    mirroredstroke.roll = stroke.roll

                    (mirroredstroke.proj_pos, _, mirroredstroke.proj_uv,
                     mirroredstroke.proj_prim, mirroredstroke.hit) = project_point_dir(
                        node=node,
                        mouse_point=mirroredstroke.pos,
                        mouse_dir=mirroredstroke.dir,
                        intersect_geometry=self.get_intersection_geometry(node),
                        plane_center=self.last_intersection_pos
                    )

                    if mirroredstroke.hit:
                        self.last_intersection_pos = mirroredstroke.proj_pos

                    # log_stroke_event(f"Mirrored stroke pre-encode: `{mirroredstroke.__dict__}`")
                    mirror_data.add(mirroredstroke.encode(), vsu.ByteStream)

                bytedata_decoded = self.to_hbytes(mirror_data).decode("utf-8")
                params.data.set(bytedata_decoded)

                try:
                    params.metadata.set(stroke_meta_data)
                except AttributeError:
                    log_stroke_event(f"Could not set metadata parameter")
                    pass

            self.strokes_next_to_encode = len(self.strokes)

    def stroke_from_event(self, ui_event: hou.ViewerEvent, device: hou.UIEventDevice, node: hou.Node) -> StrokeData:
        """Create a stroke data struct from a UI device event and mouse point projection on the geometry

        Used internally.
        """
        # log_stroke_event(f"Stroke from event: ui_event: `{ui_event}`, device: `{device}`, node: `{node}`")

        sdata = StrokeData.create()
        (mouse_point, mouse_dir) = ui_event.screenToRay(device.mouseX(), device.mouseY())

        sdata.pos = mouse_point
        sdata.dir = mouse_dir
        sdata.pressure = device.tabletPressure()
        sdata.tile = device.tabletTilt()
        sdata.angle = device.tabletAngle()
        sdata.roll = device.tabletRoll()

        if device.time() >= 0:
            sdata.time = device.time() - self.epoch_time
        else:
            sdata.time = self.stopwatch.elapsed()

        (
            sdata.proj_pos,
            _,
            sdata.proj_uv,
            sdata.proj_prim,
            sdata.hit
        ) = project_point_dir(
            node,
            sdata.pos,
            sdata.dir,
            self.get_intersection_geometry(
                node
            )
        )
        return sdata

    def handle_stroke_event(self, ui_event: hou.ViewerEvent, node: hou.Node) -> None:
        """Registers stroke event(s) and deals with the queued devices.

        Used internally.
        """
        first_device = ui_event.device()
        if ui_event.hasQueuedEvents() is True:
            first_device = ui_event.queuedEvents()[0]

        if len(self.strokes) == 0:
            if first_device.time() >= 0:
                self.epoch_time = first_device.time()
            else:
                # self.stopwatch.stop()
                self.stopwatch.start()

        for qevent in ui_event.queuedEvents():
            sd = self.stroke_from_event(ui_event, qevent, node)
            self.strokes.append(sd)

        sd = self.stroke_from_event(ui_event, ui_event.device(), node)

        if ui_event.reason() == hou.uiEventReason.Changed and self.strokes:
            sd.pressure = self.strokes[-1].pressure
            sd.tilt = self.strokes[-1].tilt
            sd.angle = self.strokes[-1].angle
            sd.roll = self.strokes[-1].roll

        self.strokes.append(sd)

    def cache_strokes(self, node: hou.Node) -> None:
        """Store the drawn stroke in the data parameter.

        Used with post-stroke callback.
        """
        new_geo = hou.Geometry()
        stroke_data_parm = node.parm(self.get_strokecache_parm_name())

        cache_geo = stroke_data_parm.evalAsGeometry()

        if cache_geo:
            new_geo.merge(cache_geo)

        incoming_stroke = node.node("STROKE_PROCESSED").geometry()

        if incoming_stroke:
            new_geo.merge(incoming_stroke)

        self.set_max_strokes_global(node, new_geo)

        clear_geo_groups(new_geo)

        stroke_data_parm.set(new_geo)

    def clear_strokecache(self, node: hou.Node) -> None:
        """Delete the contents of the hpaint data parm.
        """
        stroke_data_parm = node.parm(self.get_strokecache_parm_name())

        blank_geo = hou.Geometry()

        clear_geo_groups(blank_geo)

        stroke_data_parm.set(blank_geo)

    def reset_stroke_parms(self, node: hou.Node) -> None:
        """Delete the parm strokes from the stroke SOP.
        """
        node.parm("stroke_numstrokes").set(0)

    def add_stroke_num(self, node: hou.Node) -> None:
        """Add to the internal stroke counter on HDA used for group IDs.
        """

        strokenum_parm = node.parm(self.get_strokenum_parm_name())

        stroke_count = strokenum_parm.evalAsInt()

        stroke_count += 1

        strokenum_parm.set(stroke_count)

    def update_eraser(self, ui_event) -> None:
        """Turn on the eraser when ctrl is pressed uses eraser_enabled to bool eraser on.
        """
        if ui_event.device().isCtrlKey():
            self.eraser_enabled = True
            if ui_event.device().isShiftKey():
                self.eraser_fullstroke = True
                return
            self.eraser_fullstroke = False
            return

        self.eraser_enabled = False

    def is_pressure_enabled(self) -> bool:
        """Check whether or not pressure has been enabled on HDA.

        This is used to determine cursor radius.
        """

        return self.pressure_enabled

    def generate_text_drawable(self, scene_viewer: hou.SceneViewer) -> dict:
        """Generate all of the parameters used with the Hpaint text drawable.

        This currently uses CSS tags with <font> which may
        end up being deprecated later on.
        """

        (x, y, width, height) = scene_viewer.curViewport().size()
        margin = 10

        asset_title = "<font size=4, color=yellow><b>Hpaint v{0}</b></font>".format(HDA_VERSION)
        asset_artist = "<font size=3, color=yellow>{0}</font>".format(HDA_AUTHOR)

        text_content = "{0}<br>{1}".format(asset_title, asset_artist)
        text_params = {
            'text': text_content,
            'multi_line': True,
            'color1': hou.Color(1.0, 1.0, 0.0),
            'translate': hou.Vector3(0, height, 0),
            'origin': hou.drawableTextOrigin.UpperLeft,
            'margins': hou.Vector2(margin, -margin)
        }
        return text_params

    def set_max_strokes_global(self, node: hou.Node, input_geo: hou.Geometry) -> None:
        """Saves the current HDA stroke counter value as a global on outgoing strokes.

        Used when strokes are cached.
        """
        if input_geo is not None:
            maxiter_parm = node.parm("hp_stroke_num")
            maxiter_value = maxiter_parm.evalAsInt()

            global_name = "max_strokeid"

            self.set_global_attrib(input_geo, global_name, maxiter_value, -1)

    def set_global_attrib(self, input_geo: hou.Geometry, attrib_name: str, value: Any, default_value: Any) -> None:
        """Helper function to assign global attributes

        """
        if input_geo.findGlobalAttrib(attrib_name) is None:
            input_geo.addAttrib(hou.attribType.Global, attrib_name, default_value)
        input_geo.setGlobalAttribValue(attrib_name, value)

    def shift_surface_dist(self, node: hou.Node, direction_id: int) -> None:
        """Changes the Stroke Surface Distance parameter  when the brackets are pressed.

        Each bracket press gives the specified shift in one direction.
        """

        # edit this value to edit how the shift is applied
        shift_val = 0.005

        sdist_parm = node.parm('hp_stroke_sdist')

        sdist_parm_val = sdist_parm.evalAsFloat()

        # 0 = down, 1 = up
        if direction_id == 0:
            result_val = sdist_parm_val - shift_val

            if result_val <= 0.0:
                result_val = 0.0

            sdist_parm.set(result_val)
        else:
            result_val = sdist_parm_val + shift_val

            sdist_parm.set(result_val)

    def undoblock_open(self, block_name: str) -> None:
        """Open up an undo block safely without chance of a conflict
        """
        if self.undo_state == 0:
            try:
                self.cursor_adv.scene_viewer.beginStateUndo(block_name)
                self.undo_state = 1
            except hou.OperationFailed:
                return
        elif self.undo_state:
            self.cursor_adv.scene_viewer.endStateUndo()
            try:
                self.cursor_adv.scene_viewer.beginStateUndo(block_name)
                self.undo_state = 1
            except hou.OperationFailed:
                return

    def undoblock_close(self) -> None:
        """ Close the active undo block and prevent a new undo block from being generated
        """
        if self.undo_state == 0:
            return
        elif self.undo_state:
            self.cursor_adv.scene_viewer.endStateUndo()
            self.undo_state = 0


def log_stroke_event(log_string: str, use_print: bool = True, level: int = logging.INFO) -> None:
    if use_print:
        print(f"{log_string}")
    else:
        logging.log(level=level, msg=log_string)


def clear_geo_groups(geo: hou.Geometry) -> None:
    for group in geo.primGroups():
        if group.primCount() < 1:
            try:
                group.destroy()
            except hou.GeometryPermissionError:
                log_stroke_event(f"Could not destroy group `{group}`.")


def createViewerStateTemplate():
    """Mandatory entry point to create and return the viewer state
    template to register.

    This contains the standardised keyword arguments 'kwargs' for the createViewerStateTemplate function
    specified in the Houdini documentation.
    """

    state_typename = kwargs["type"].definition().sections()["DefaultState"].contents()
    state_label = "aaron_smith::hpaint::{0}".format(HDA_VERSION)
    state_cat = hou.sopNodeTypeCategory()

    template = hou.ViewerStateTemplate(state_typename, state_label, state_cat)
    template.bindFactory(State)
    template.bindIcon(kwargs["type"].icon())

    # hotkeys for menu
    press_save_to_file = vsu.hotkey(state_typename, 'press_save_to_file', 'shift+s', 'Save Buffer to Disk')
    press_clear_buffer = vsu.hotkey(state_typename, 'press_clear_buffer', 'shift+c', 'Clear Stroke Buffer')
    toggle_guide_vis = vsu.hotkey(state_typename, 'toggle_guide_vis', 'g', 'Toggle Guide Visibility')
    toggle_screen_draw = vsu.hotkey(state_typename, 'toggle_screen_draw', 'shift+d', 'Toggle Screen Draw')

    stroke_sdshift_down = vsu.hotkey(state_typename, 'stroke_sdshift_down', '[', 'Shift Surface Dist Down')
    stroke_sdshift_up = vsu.hotkey(state_typename, 'stroke_sdshift_up', ']', 'Shift Surface Dist Up')

    action_by_group = vsu.hotkey(state_typename, 'action_by_group', 'a', 'Toggle Action By Group')

    # add menu for hpaint commands
    hpaint_menu = hou.ViewerStateMenu('hpaint_menu', 'Hpaint settings...')

    hpaint_menu.addActionItem('press_save_to_file', 'Save Buffer to Disk', hotkey=press_save_to_file)
    hpaint_menu.addActionItem('press_clear_buffer', 'Clear Stroke Buffer', hotkey=press_clear_buffer)
    hpaint_menu.addActionItem('toggle_guide_vis', 'Toggle Guide Visibility', hotkey=toggle_guide_vis)
    hpaint_menu.addActionItem('toggle_screen_draw', 'Toggle Screen Draw', hotkey=toggle_screen_draw)

    # shift the stroke surface distance up or down
    hpaint_menu.addActionItem('stroke_sdshift_down', 'Shift Surface Dist Down', hotkey=stroke_sdshift_down)
    hpaint_menu.addActionItem('stroke_sdshift_up', 'Shift Surface Dist Up', hotkey=stroke_sdshift_up)

    hpaint_menu.addActionItem('action_by_group', 'Toggle Action By Group', hotkey=action_by_group)

    template.bindMenu(hpaint_menu)

    return template
