"""
State:          Hpaint 1.2
State type:     aaron_smith::hpaint::1.2
Description:    Viewer state for Hpaint
Author:         Aaron Smith
Date Created:   August 26, 2021 - 11:32:36
"""

import hou
import viewerstate.utils as vsu

"""
Thank you for downloading this HDA and spreading the joy of drawing in Houdini.
Hpaint was lovingly made in my free time, if you have any questions please email
me at aaron@aaronsmith.tv, or consider taking a look at the rest of my work at
https://aaronsmith.tv. 

For future updates: https://github.com/aaronsmithtv/hpaint
"""

HDA_VERSION = 1.2
HDA_AUTHOR = "aaronsmith.tv"


class StrokeParams(object):
    """Stroke instance parameters.

    The class holds the stroke instance parameters as attributes for a given
    stroke operator and instance number.

    Parameters can be accessed as follows:

    params = StrokeParams(node, 55)
    params.colorr.set(red)
    params.colorg.set(green)
    etc...
    """

    def __init__(self, node, inst):
        self.inst = inst
        param_name = 'stroke' + str(inst)
        prefix_len = len(param_name) + 1

        def valid_parm(vparm):
            return vparm.isMultiParmInstance() and vparm.name().startswith(param_name)

        params = filter(valid_parm, node.parms())
        for p in params:
            self.__dict__[p.name()[prefix_len:]] = p


class StrokeData(object):
    """Holds the stroke data.

    Store the stroke's data within class to recall attributes that vary/change across a stroke

    Attributes that do not change across the length of a stroke are stored as metadata
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
            proj_success=False,
            pressure=1.0,
            time=0.0,
            tilt=0.0,
            angle=0.0,
            roll=0.0,
        )

    def reset(self):
        self.pos = hou.Vector3(0.0, 0.0, 0.0)
        self.dir = hou.Vector3(0.0, 0.0, 0.0)
        self.proj_pos = hou.Vector3(0.0, 0.0, 0.0)
        self.proj_uv = hou.Vector3(0.0, 0.0, 0.0)
        self.proj_prim = -1
        self.proj_success = False
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
        stream.add(self.proj_success, bool)
        return stream

    def decode(self, stream):
        pass


class StrokeMetaData(object):
    """Holds the meta data from the stroke state client node.

    These are translated into primitive attributes by the Stroke SOP.
    The default behaviour if this state is to copy any stroke_ prefixed
    parameters into this meta data, but the buildMetaDataArray can
    be overridden to add additional information.
    """

    def __init__(self):
        self.name = None
        self.size = 0
        self.type = None
        self.value = None

    @staticmethod
    def create(node, meta_data_array):
        """
                Creates an array of StrokeMetaData from the client node parameters and
                converts it to a json string
                """
        import json

        # insert number of total elements
        meta_data_array.insert(0, len(meta_data_array))

        if len(meta_data_array) == 1:
            meta_data_array.append({})

        return json.dumps(meta_data_array)

    @staticmethod
    def build_parms(node):
        """
                Returns an array of stroke parameters to consider for meta data
                """
        import parmutils

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


class StrokeCursorAdv(object):
    """
        Implements the brush cursor used by the stroke state.

        Handles the creation of the advanced drawable, and provides methods
        for various transform operations.

        Use self.drawable to edit drawable parameters such as the colour, and glow width.
        """

    def __init__(self, scene_viewer, state_name):
        self.mouse_xform = hou.Matrix4()

        self.scene_viewer = scene_viewer
        self.state_name = state_name

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
        self.last_pos = hou.Vector3()

        # display prompt when entering the viewer state
        self.prompt = "Left click to draw strokes. Ctrl+Left to erase strokes, Ctrl+Shift+Left to delete strokes. Shift drag to change stroke size."

        # control for whether drawing should be disabled (to allow resizing operation)
        self.resizing = False

    def init_brush(self):
        """Create the advanced drawable and return it to self.drawable
        """
        sops = hou.sopNodeTypeCategory()
        verb = sops.nodeVerb('sphere')

        verb.setParms({
            "type": 2,
            "orient": 1,
            "rows": 13,
            "cols": 24
        })

        cursor_geo = hou.Geometry()
        verb.execute(cursor_geo, [])

        cursor_draw = hou.GeometryDrawableGroup("cursor")

        # adds the drawables
        cursor_draw.addDrawable(hou.GeometryDrawable(self.scene_viewer,
                                                     hou.drawableGeometryType.Face, "face",
                                                     params={'color1': (0.0, 1.0, 0.0, 1.0),
                                                             'color2': (0.0, 0.0, 0.0, 0.33),
                                                             'highlight_mode': hou.drawableHighlightMode.MatteOverGlow,
                                                             'glow_width': 2}))

        cursor_draw.setGeometry(cursor_geo)

        return cursor_draw

    def set_color(self, color):
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

    def project_point(self, node, mouse_point, mouse_dir, intersect_geometry):
        """Performs a geometry intersection and returns a tuple with the intersection info.

        point: intersection point
        normal: intersection point normal
        uvw: parametric coordinates
        prim_num: intersection primitive number
        hit_success: return True if operation is successful or False otherwise
        """
        proj_type = _eval_param(node, "stroke_projtype", 0)
        proj_center = _eval_param_v3(node, "stroke_projcenterx", "stroke_projcentery", "stroke_projcenterz", (0, 0, 0))
        proj_dir = _projection_dir(proj_type, mouse_dir)
        prim_num = -1
        uvw = hou.Vector3(0.0, 0.0, 0.0)

        try:
            hit_point_plane = hou.hmath.intersectPlane(proj_center, proj_dir, mouse_point, mouse_dir)
        except Exception:
            hit_point_plane = hou.Vector3()

        hit = True
        if proj_type > 3:
            if intersect_geometry is not None:
                hit_point_geo = hou.Vector3()
                normal = hou.Vector3()

                prim_num = intersect_geometry.intersect(mouse_point, mouse_dir, hit_point_geo, normal, uvw, None, 0,
                                                        1e18, 5e-3)
                if prim_num >= 0:
                    return hit_point_geo, normal, uvw, prim_num, True
            # Failed hit or no intersection geometry.
            hit = False
        return hit_point_plane, None, uvw, prim_num, hit

    def update_position(self, node, mouse_point, mouse_dir, rad, intersect_geometry):
        """Overwrites the model transform with an intersection of cursor to geo.
        also records if the intersection is hitting geo, and which prim is recorded in the hit
        """
        (cursor_pos, normal, uvw, prim_num, hit) = self.project_point(node, mouse_point, mouse_dir, intersect_geometry)

        # update self.is_hit for geo masking
        self.is_hit = hit
        self.hit_prim = prim_num

        self.last_pos = cursor_pos

        # Position is at the intersection point oriented to go along the normal
        srt = {
            'translate': (self.last_pos[0], self.last_pos[1], self.last_pos[2]),
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

    def update_xform(self, srt):
        """ Overrides the current transform with the given dictionary.
        The entries should match the keys of hou.Matrix4.explode.
        """
        try:
            current_srt = self.xform.explode()
            current_srt.update(srt)
            self.xform = hou.hmath.buildTransform(current_srt)
            self.drawable.setTransform(self.xform * self.model_xform)
        except hou.OperationFailed:
            return

    def update_model_xform(self, viewport):
        """ Update our model_xform from the selected viewport.
        This will vary depending on our position type.
        """

        self.model_xform = viewport.modelToGeometryTransform().inverted()
        self.mouse_xform = hou.Matrix4(1.0)

    def render(self, handle):
        """Renders the cursor in the viewport with the onDraw python state

        optimise the onDraw method by reducing the amount of operations
        calculated at draw time as possible
        """
        self.drawable.draw(handle)

    def show_prompt(self):
        """Write the tool prompt used in the viewer state
        """
        self.scene_viewer.setPromptMessage(self.prompt)


def _eval_param(node, param, default):
    """ Evaluates param on node, if it doesn't exist return default.
    """
    try:
        return node.evalParm(param)
    except Exception:
        return default


def _eval_param_v3(node, param1, param2, param3, default):
    """Evaluates vector3 param on node, if it doesn't exist return default.
    """
    try:
        return hou.Vector3(
            node.evalParm(param1), node.evalParm(param2), node.evalParm(param3))
    except Exception:
        return hou.Vector3(default)


def _eval_param_c(node, param1, param2, param3, default):
    """Evaluates color param on node, if it doesn't exist return default.
    """
    try:
        return hou.Color(
            node.evalParm(param1), node.evalParm(param2), node.evalParm(param3))
    except Exception:
        return hou.Color(default)


def _projection_dir(proj_type, screen_space_projection_dir):
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


class State(object):
    """Stroke state implementation to handle the mouse/tablet interaction.
    """

    RESIZE_ACCURATE_MODE = 0.2

    def __init__(self, state_name, scene_viewer):
        self.__dict__.update(kwargs)

        self.state_name = state_name
        self.scene_viewer = scene_viewer

        self.strokes = []
        self.strokesMirrorData = []
        self.strokesNextToEncode = 0
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
        self.geo_mask = True

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

        # text draw generation
        self.text_params = self.generate_text_drawable(self.scene_viewer)

    def onPreStroke(self, node, ui_event, captured_parms):
        """Called when a stroke is started.
        Override this to setup any stroke_ parameters.
        """

        vsu.triggerParmCallback("prestroke", node, ui_event.device())

    def onPostStroke(self, node, ui_event, captured_parms):
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

    def onPreApplyStroke(self, node, ui_event, captured_parms):
        """Called before new stroke values are copied.
        This is done during the stroke operation.

        Override this to do any preparation just before the stroke
        parameters are updated for an active stroke.
        """
        pass

    def onPostApplyStroke(self, node, ui_event, captured_parms):
        """Called before after new stroke values are copied. This is done
        during the stroke operation.

        Override this to do any clean up for every stroke
        update. This can be used to break up a single stroke
        into a series of operations, for example.
        """
        pass

    def onPreMouseEvent(self, node, ui_event, captured_parms):
        """Called at the start of every mouse event.

        This is outside of undo blocks, so do not
        set parameters without handling undos.

        Override this to inject code just before all mouse event
        processing
        """
        pass

    def onPostMouseEvent(self, node, ui_event, captured_parms):
        """Called at the end of every mouse event.

        This is outside of undo blocks, so do not
        set parameters without handling undos.

        Override this to inject code just after all mouse event
        processing
        """
        pass

    def buildMetaDataArray(self, node, ui_event, captured_parms, mirrorxform):
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

    def onEnter(self, kwargs):
        """Called whenever the state begins.

        Override this to perform any setup, such as visualizers,
        that should be active whenever the state is.
        """

        node = kwargs['node']

        # replaced STROKECURSOR.size with float value
        # initialise the cursor radius
        rad = _eval_param(node, self.radiusParmName(node), 0.05)
        self.cursor_adv.update_xform({'scale': (rad, rad, rad)})
        # hide the cursor before it has inherited a screen transform
        self.cursor_adv.hide()

        # pre-build a list of meta data parameters from the node
        self.meta_data_parms = StrokeMetaData.build_parms(node)

        # display the viewer state prompt
        self.cursor_adv.show_prompt()

    def onExit(self, kwargs):
        """Called whenever the state ends.

        Override this to perform any cleanup, such as visualizers,
        that should be finished whenever the state is.
        """
        vsu.Menu.clear()

    def onMouseEvent(self, kwargs):
        """Process mouse events
        """

        ui_event = kwargs['ui_event']
        node = kwargs['node']

        # captured parms?
        captured_parms = {key: kwargs.get(key, None) for key in self.capture_parms}

        # record a mouse position + direction from the ui_event
        (self.mouse_point, self.mouse_dir) = ui_event.ray()

        # logic for applying tablet pressure to cursor radius, and
        # updating the cursor transform in 3d space
        # check if there are no device events in the queue
        if not ui_event.hasQueuedEvents():
            if not self.cursor_adv.resizing:
                # evaluate the radius parameter for a 'default' radius value
                radius_parmval = _eval_param(node, self.radiusParmName(node), 0.05)
                if ui_event.device().isLeftButton() and len(self.strokes) > 0:
                    if self.is_pressure_enabled(node):
                        # if a stroke currently exists, update the default radius value
                        # with a multiplication of the current tablet pressure
                        pressure_rad = self.strokes[-1].pressure
                        radius_parmval *= pressure_rad

                self.cursor_adv.update_model_xform(ui_event.curViewport())
                self.cursor_adv.update_position(node, mouse_point=self.mouse_point,
                                                mouse_dir=self.mouse_dir, rad=radius_parmval,
                                                intersect_geometry=self.intersectGeometry(node))

        # display the cursor after xform applied
        self.cursor_adv.show()

        # SHIFT DRAG RESIZING
        started_resizing = False
        # check shift (resize key) is not conflicting with eraser keys
        if ui_event.reason() == hou.uiEventReason.Start and ui_event.device().isShiftKey() and not ui_event.device().isCtrlKey():
            # if stroke has begun, enable resizing and cache mouse position
            self.cursor_adv.resizing = True
            started_resizing = True
            self.last_mouse_x = ui_event.device().mouseX()
            self.last_mouse_y = ui_event.device().mouseY()

        if self.cursor_adv.resizing:
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

            return

        # update the state of eraser usage
        self.update_eraser(ui_event, node)

        if not self.eraser_enabled:
            # set cursor colour
            cursor_cr = node.parm('hp_colourr').eval()
            cursor_cg = node.parm('hp_colourg').eval()
            cursor_cb = node.parm('hp_colourb').eval()
            cursor_ca = node.parm('hp_coloura').eval()

            cursor_color = hou.Vector4(cursor_cr, cursor_cg, cursor_cb, cursor_ca)

            self.cursor_adv.set_color(cursor_color)
        else:
            # set eraser colour
            self.cursor_adv.set_color(hou.Vector4(1.0, 0.0, 0.0, 1.0))

        self.handle_stroke_event(ui_event, node)

        # Geometry masking system
        # If the cursor moves off of the geometry during a stroke draw - a new stroke is created.
        # New strokes cannot be created off draw
        if not self.eraser_enabled:
            if self.geo_mask:
                self.stroke_interactive_mask(ui_event, node, captured_parms)
                return

            # If geometry masking is disabled, hits are not accounted for
            # Using a simplified version of the sidefx_stroke.py method
            else:
                self.stroke_interactive(ui_event, node, captured_parms)
                return
        else:
            self.eraser_interactive(ui_event, node, captured_parms)
            return

    def onMouseWheelEvent(self, kwargs):
        """Called whenever the mouse wheel moves.

        Default behaviour is to resize the cursor.

        Override this to do different things on mouse wheel.
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

    def onResume(self, kwargs):
        """Called whenever the state is resumed from an interruption.
        """
        self.cursor_adv.show()
        self.cursor_adv.show_prompt()

        self.log('cursor = ', self.cursor_adv)

    def onInterrupt(self, kwargs):
        """Called whenever the state is temporarily interrupted.
        """
        self.cursor_adv.hide()

    def onMenuAction(self, kwargs):
        """Called when a state menu is selected.
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

    def onDraw(self, kwargs):
        """Called every time the viewport renders.
        """

        # draw the text in the viewport upper left
        handle = kwargs['draw_handle']

        self.text_drawable.draw(handle, self.text_params)

        # draw the cursor
        self.cursor_adv.render(handle)

    def radiusParmName(self, node):
        """Returns the parameter name for determining the current radius of the brush.
        """
        return 'stroke_radius'

    def strokecacheParmName(self, node):
        """Returns the name of the hpaint strokecache
        """
        return 'hp_strokecache'

    def strokenumParmName(self, node):
        """Returns the name of the hpaint strokecache
        """
        return 'hp_stroke_num'

    def intersectGeometry(self, node):
        """Returns the geometry to use for intersections of the ray.
        """
        proj_type = _eval_param(node, "stroke_projtype", 0)

        if proj_type > 3:
            if len(node.inputs()) and node.inputs()[0] is not None:
                # check if intersect is being used as eraser or pen
                if not self.eraser_enabled:
                    isectnode = node.node("INPUT_GEO")
                else:
                    isectnode = node.node("STROKE_READIN")
                if self.intersect_geometry is None:
                    self.intersect_geometry = isectnode.geometry()
                else:
                    # Check to see if we have already cached this.
                    if self.intersect_geometry.sopNode() != isectnode:
                        self.intersect_geometry = isectnode.geometry()
            else:
                self.intersect_geometry = None
        return self.intersect_geometry

    def activeMirrorTransforms(self, node) -> hou.Matrix4:
        """Returns a list of active transforms to mirror the incoming strokes with.

        The first should be identity to represent passing through.
        If an empty list, no strokes will be recorded.

        Override this to add mirror transforms.
        """
        result = hou.Matrix4()
        result.setToIdentity()
        return [result]

    def stroke_interactive_mask(self, ui_event, node, captured_parms):
        """The logic for drawing a stroke, opening/closing undo blocks, and assigning prestroke / poststroke callbacks.

        The 'mask' variation of stroke_interactive uses the
        'is hit' attribute of the drawable cursor to close
        strokes that are drawn off the edge of the mask geo.
        """
        if ui_event.reason() == hou.uiEventReason.Active or ui_event.reason() == hou.uiEventReason.Start:
            if self.first_hit is True:
                if self.cursor_adv.is_hit:
                    self.undoblock_open('Draw Stroke')

                    self.reset_active_stroke()

                    # BEGIN NEW STROKE
                    self.onPreStroke(node, ui_event, captured_parms)
                    self.apply_stroke(node, ui_event, False, captured_parms)

                    self.first_hit = False
                else:
                    return
            else:
                if self.cursor_adv.is_hit:
                    self.apply_stroke(node, ui_event, True, captured_parms)
                else:
                    self.reset_active_stroke()

                    self.first_hit = True

                    # END STROKE
                    self.onPostStroke(node, ui_event, captured_parms)
                    self.undoblock_close()

        # when the mouse is released, apply the final update and reset the stroke
        elif ui_event.reason() == hou.uiEventReason.Changed:
            if self.first_hit is False:
                if self.cursor_adv.is_hit:
                    self.apply_stroke(node, ui_event, True, captured_parms)
                    self.reset_active_stroke()

                    self.first_hit = True

                    # END STROKE
                    self.onPostStroke(node, ui_event, captured_parms)
                    self.undoblock_close()
                else:
                    self.reset_active_stroke()

                    self.first_hit = True

                    # END STROKE
                    self.onPostStroke(node, ui_event, captured_parms)
                    self.undoblock_close()

    def stroke_interactive(self, ui_event, node, captured_parms):
        """The logic for drawing a stroke, opening/closing undo blocks, and assigning prestroke / poststroke callbacks.
        """
        if ui_event.reason() == hou.uiEventReason.Active or ui_event.reason() == hou.uiEventReason.Start:
            if self.first_hit is True:
                self.undoblock_open('Draw Stroke')

                self.reset_active_stroke()

                # BEGIN NEW STROKE
                self.onPreStroke(node, ui_event, captured_parms)
                self.apply_stroke(node, ui_event, False, captured_parms)

                self.first_hit = False
            else:
                self.apply_stroke(node, ui_event, True, captured_parms)

        # when the mouse is released, apply the final update and reset the stroke
        elif ui_event.reason() == hou.uiEventReason.Changed:
            if self.first_hit is False:
                self.apply_stroke(node, ui_event, True, captured_parms)
                self.reset_active_stroke()

                self.first_hit = True

                # END STROKE
                self.onPostStroke(node, ui_event, captured_parms)
                self.undoblock_close()

    def eraser_interactive(self, ui_event, node, captured_parms):
        """ The logic for erasing as a stroke, and opening an eraser-specific undo block.
        """
        if ui_event.reason() == hou.uiEventReason.Active or ui_event.reason() == hou.uiEventReason.Start:
            if self.first_hit is True:
                self.undoblock_open('Eraser')
                self.first_hit = False

            if self.cursor_adv.is_hit and self.cursor_adv.hit_prim >= 0:

                intersect_geometry = self.intersectGeometry(node)

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
                    stroke_data_parm = node.parm(self.strokecacheParmName(node))
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

    def resize_cursor(self, node, dist):
        """ Adjusts the current stroke radius by a requested bump.

        Used internally.
        """
        scale = pow(1.01, dist)
        stroke_radius = node.parm(self.radiusParmName(node))

        rad = stroke_radius.evalAsFloat()
        rad *= scale

        stroke_radius.set(rad)
        self.cursor_adv.update_xform({'scale': (rad, rad, rad)})

    def bytes(self, mirrorData):
        """Encodes the list of StrokeData as an array of bytes and returns in a fashion the Stroke SOP expects.

        Used internally.
        """
        stream = vsu.ByteStream()
        stream.add(StrokeData.VERSION, int)
        stream.add(len(self.strokes), int)
        stream.add(mirrorData, vsu.ByteStream)
        return stream.data()

    def reset_active_stroke(self):
        self.strokes = []
        self.strokesMirrorData = []
        self.strokesNextToEncode = 0

    def apply_stroke(self, node, ui_event, update, captured_parms):
        """Updates the stroke multiparameter from the current self.strokes information.

        Used internally.
        """
        stroke_numstrokes_param = node.parm('stroke_numstrokes')

        # Performs the following as undoable operations
        with hou.undos.group("Draw Stroke"):
            # self.onPreApplyStroke(node, ui_event, captured_parms)

            stroke_numstrokes = stroke_numstrokes_param.evalAsInt()
            stroke_radius = _eval_param(node, self.radiusParmName(node), 0.05)
            stroke_opacity = _eval_param(node, 'stroke_opacity', 1)
            stroke_tool = _eval_param(node, 'stroke_tool', -1)
            stroke_color = _eval_param_c(node, 'stroke_colorr', 'stroke_colorg', 'stroke_colorb', (1, 1, 1))
            stroke_projtype = _eval_param(node, 'stroke_projtype', 0)
            stroke_projcenter = _eval_param_v3(node, 'stroke_projcenterx', 'stroke_projcentery', 'stroke_projcenterz',
                                               (0, 0, 0))

            proj_dir = _projection_dir(stroke_projtype, self.mouse_dir)

            mirrorlist = self.activeMirrorTransforms(node)

            if stroke_numstrokes == 0 or not update:
                stroke_numstrokes += len(mirrorlist)

            stroke_numstrokes_param.set(stroke_numstrokes)

            activestroke = stroke_numstrokes - len(mirrorlist) + 1

            # users should use reset_active_stroke to reset it
            # this check might catch if self.strokes was set to empty
            if self.strokesNextToEncode > len(self.strokes):
                self.strokesNextToEncode = 0
                self.strokesMirrorData = []

            # check if cache array has enough size
            extraMirrors = len(mirrorlist) - len(self.strokesMirrorData)
            if extraMirrors > 0:
                self.strokesMirrorData.extend(
                    [vsu.ByteStream() for _ in range(extraMirrors)])

            for (mirror, mirrorData) in zip(mirrorlist, self.strokesMirrorData):
                meta_data_array = self.buildMetaDataArray(node, ui_event, captured_parms, mirror)
                stroke_meta_data = StrokeMetaData.create(node, meta_data_array)

                # update the stroke parameter set
                params = StrokeParams(node, activestroke)
                activestroke = activestroke + 1
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

                # Mirrored stroke takes current data from mouse/tablet and stores it.
                # This stroke data is then encoded to bytes to be read by stroke SOP parms
                mirroredstroke = StrokeData.create()
                for i in range(self.strokesNextToEncode, len(self.strokes)):
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
                    mirroredstroke.proj_success = False,
                    mirroredstroke.pressure = stroke.pressure
                    mirroredstroke.time = stroke.time
                    mirroredstroke.tilt = stroke.tilt
                    mirroredstroke.angle = stroke.angle
                    mirroredstroke.roll = stroke.roll

                    mirroredstroke.normal = hou.Vector3(0.0, 0.0, 0.0)

                    (mirroredstroke.proj_pos, _, mirroredstroke.proj_uv, mirroredstroke.proj_prim,
                     mirroredstroke.proj_success) = self.cursor_adv.project_point(node, mirroredstroke.pos,
                                                                                  mirroredstroke.dir,
                                                                                  self.intersectGeometry(node))

                    mirrorData.add(mirroredstroke.encode(), vsu.ByteStream)

                # store the stroke points

                bytedata_decoded = self.bytes(mirrorData).decode("utf-8")

                params.data.set(bytedata_decoded)
                try:
                    # NOTE: the node may not have a meta data parameter
                    params.metadata.set(stroke_meta_data)
                except AttributeError:
                    pass

            self.strokesNextToEncode = len(self.strokes)

    def stroke_from_event(self, ui_event, device, node):
        """Create a stroke data struct from a UI device event and mouse point projection on the geometry

        Used internally.
        """
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

        (sdata.proj_pos, _, sdata.proj_uv, sdata.proj_prim, sdata.proj_success) = self.cursor_adv.project_point(node,
                                                                                                                sdata.pos,
                                                                                                                sdata.dir,
                                                                                                                self.intersectGeometry(
                                                                                                                    node))
        return sdata

    def handle_stroke_event(self, ui_event, node):
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

    def cache_strokes(self, node):
        """Store the drawn stroke in the data parameter.

        Used with post-stroke callback.
        """
        new_geo = hou.Geometry()
        stroke_data_parm = node.parm(self.strokecacheParmName(node))

        cache_geo = stroke_data_parm.evalAsGeometry()

        if cache_geo:
            new_geo.merge(cache_geo)

        incoming_stroke = node.node("STROKE_PROCESSED").geometry()

        if incoming_stroke:
            new_geo.merge(incoming_stroke)

        self.set_max_strokes_global(node, new_geo)

        stroke_data_parm.set(new_geo)

    def clear_strokecache(self, node):
        """Delete the contents of the hpaint data parm.
        """
        stroke_data_parm = node.parm(self.strokecacheParmName(node))

        blank_geo = hou.Geometry()

        stroke_data_parm.set(blank_geo)

    def reset_stroke_parms(self, node):
        """Delete the parm strokes from the stroke SOP.
        """
        node.parm("stroke_numstrokes").set(0)

    def add_stroke_num(self, node):
        """Add to the internal stroke counter on HDA used for group IDs.
        """

        strokenum_parm = node.parm(self.strokenumParmName(node))

        stroke_count = strokenum_parm.evalAsInt()

        stroke_count += 1

        strokenum_parm.set(stroke_count)

    def update_eraser(self, ui_event, node):
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

    def is_pressure_enabled(self, node):
        """Check whether or not pressure has been enabled on HDA.

        This is used to determine cursor radius.
        """
        result = True

        return result

    def generate_text_drawable(self, scene_viewer):
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
            'margins': hou.Vector2(margin, -margin)}

        return text_params

    def set_max_strokes_global(self, node, input_geo):
        """Saves the current HDA stroke counter value as a global on outgoing strokes.

        Used when strokes are cached.
        """
        if input_geo is not None:
            maxiter_parm = node.parm("hp_stroke_num")
            maxiter_value = maxiter_parm.evalAsInt()

            global_name = "max_strokeid"

            self.set_global_attrib(input_geo, global_name, maxiter_value, -1)

    def set_global_attrib(self, input_geo, attrib_name, value, default_value):
        """Helper function to assign global attributes

        """
        if input_geo.findGlobalAttrib(attrib_name) is None:
            input_geo.addAttrib(hou.attribType.Global, attrib_name, default_value)
        input_geo.setGlobalAttribValue(attrib_name, value)

    def shift_surface_dist(self, node, direction_id):
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

    def undoblock_open(self, block_name):
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

    def undoblock_close(self):
        """ Close the active undo block and prevent a new undo block from being generated
        """
        if self.undo_state == 0:
            return
        elif self.undo_state:
            self.cursor_adv.scene_viewer.endStateUndo()
            self.undo_state = 0


def createViewerStateTemplate():
    """Mandatory entry point to create and return the viewer state
    template to register.
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
