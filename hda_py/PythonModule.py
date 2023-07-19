import fnmatch
import glob
import os
import re
import typing

import hou


def clear_geo_groups(geo: hou.Geometry) -> None:
    # if geo is None:
    #     return

    for group in geo.primGroups():
        if group.primCount() < 1:
            try:
                group.destroy()
            except hou.GeometryPermissionError:
                continue


def clear_geo_attribs(geo: hou.Geometry) -> None:
    # if geo is None:
    #     return

    pt_attribs = geo.pointAttribs()
    prim_attribs = geo.primAttribs()
    vtx_attribs = geo.vertexAttribs()
    dt_attribs = geo.globalAttribs()

    for attrib in pt_attribs + prim_attribs + vtx_attribs + dt_attribs:
        try:
            attrib.destroy()
        except hou.OperationFailed:
            continue


def clear_strokecache(node: hou.Node):
    """Delete the contents of the hpaint data parm"""
    stroke_data_parm = node.parm(get_strokecache_name(node))

    blank_geo = hou.Geometry()
    clear_geo_groups(blank_geo)
    clear_geo_attribs(blank_geo)

    stroke_data_parm.set(blank_geo)
    node.parm("hp_file_reload").pressButton()


def clear_stroke_buffer(node: hou.Node):
    """Callback associated with the 'clear stroke buffer' parm"""

    stroke_data_parm = node.parm(get_strokecache_name(node))

    isogrp_toggle = node.parm(get_actiontoggle_name(node)).evalAsInt()

    isogrp_query = node.parm(get_actiongrp_name(node)).evalAsString()

    if isogrp_toggle:
        new_geo = hou.Geometry()
        clear_geo_groups(new_geo)
        clear_geo_attribs(new_geo)

        stroke_geo = stroke_data_parm.evalAsGeometry()

        if stroke_geo:
            new_geo.merge(stroke_geo)

        # use unix filematch syntax to find groups eligible for deletion
        del_groups = find_multi_groups(new_geo, isogrp_query)

        new_geo = isolate_multigroups_v2(new_geo, del_groups)

        clear_geo_attribs(new_geo)
        clear_geo_groups(new_geo)

        stroke_data_parm.set(new_geo)

    else:
        blank_geo = hou.Geometry()
        clear_geo_groups(blank_geo)
        clear_geo_attribs(blank_geo)
        stroke_data_parm.set(blank_geo)
        return


def file_change_callback(node: hou.Node):
    """
    When loading in a disk cache, overwrite the HDA's
    stroke counter value with max_strokeid global (if
    the global is higher than the counter)
    """
    update_filecache(node)
    global_name = "max_strokeid"

    maxiter_parm = node.parm("hp_stroke_num")
    hda_maxiter_val = maxiter_parm.evalAsInt()

    diskcache_geo = get_filecache_geo(node)

    # overwrite the max strokes parm if disk global is higher value
    diskcache_maxiter_val = -1

    if diskcache_geo is not None:
        if diskcache_geo.findGlobalAttrib(global_name) is not None:
            diskcache_maxiter_val = diskcache_geo.attribValue(global_name)

    if diskcache_maxiter_val > hda_maxiter_val:
        with hou.undos.disabler():
            maxiter_parm.set(diskcache_maxiter_val)


def save_cached_strokes(node: hou.Node):
    """
    i/o operation for saving strokes currently in the stroke
    buffer to disk
    """

    filepath_eval(node)

    stroke_data_parm = node.parm(get_strokecache_name(node))
    stroke_cache = stroke_data_parm.evalAsGeometry()
    # check if stroke buffer has any geo
    if stroke_cache:
        geopath = node.parm(get_filepath_name(node)).evalAsString()
        geopath = hou.text.normpath(geopath)
        geopath = hou.text.abspath(geopath)

        filepath = geopath.rsplit("/", 1)[0]
        # check file path and raise any windows error

        if not os.path.exists(filepath):
            try:
                os.makedirs(filepath)
            except OSError:
                if not os.path.isdir(filepath):
                    raise
        # choose whether to merge into current file or save a new file
        if os.path.exists(geopath):
            # load the geometry from disk and merge into an editable geo
            c_geo = hou.Geometry()
            clear_geo_attribs(c_geo)
            c_geo.loadFromFile(str(geopath))
            c_geo.merge(stroke_cache)

            # overwrite stroke cache on disk with a higher max_strokeid
            # if the HDA's stroke counter is higher than disk cache global
            maxiter_parm = node.parm("hp_stroke_num")
            hda_maxiter_val = maxiter_parm.evalAsInt()

            sid_global_name = "max_strokeid"

            if c_geo is not None:
                if c_geo.findGlobalAttrib(sid_global_name) is not None:
                    c_geo_maxiter_val = c_geo.attribValue(sid_global_name)

                    if hda_maxiter_val > c_geo_maxiter_val:
                        c_geo.setGlobalAttribValue(sid_global_name, hda_maxiter_val)

            # need to add attrib if it does not exist?
            try:
                with hou.undos.disabler():
                    c_geo.saveToFile(str(geopath))
                    clear_strokecache(node)
                    # load new saved cached into disk cache data parm
                    update_filecache(node)
            except hou.OperationFailed:
                hou.ui.displayMessage("Hpaint: Failed to overwrite disk file")
        else:
            try:
                with hou.undos.disabler():
                    stroke_cache.saveToFile(str(geopath))
                    clear_strokecache(node)
                    # load new saved cached into disk cache data parm
                    update_filecache(node)
            except hou.OperationFailed:
                hou.ui.displayMessage("Hpaint: Failed to save to disk")


def delete_filecache(node: hou.Node):
    """
    Delete the contents of the pathed file on disk
    """

    confirm = hou.ui.displayConfirmation(
        "Delete the stroke file cache on disk?",
        suppress=hou.confirmType.OverwriteFile,
    )

    if confirm:
        filepath_eval(node)

        geopath = node.parm(get_fpe_name(node)).evalAsString()
        geopath = hou.text.normpath(geopath)
        geopath = hou.text.abspath(geopath)

        if not os.path.exists(geopath):
            return

        c_geo = hou.Geometry()
        clear_geo_attribs(c_geo)

        try:
            c_geo.loadFromFile(geopath)
            load_success = True
        except (hou.OperationFailed, hou.GeometryPermissionError):
            load_success = False

        if load_success:
            os.remove(geopath)

        node.parm("hp_file_reload").pressButton()


def clear_filecache(node: hou.Node):
    """
    Delete the contents of the pathed file on disk
    """

    isogrp_toggle = node.parm(get_actiontoggle_name(node)).evalAsInt()
    isogrp_query = node.parm(get_actiongrp_name(node)).evalAsString()

    if isogrp_toggle:
        confirm = hou.ui.displayConfirmation(
            "Clear strokes matching the group pattern {0} on disk?".format(
                isogrp_query
            ),
            suppress=hou.confirmType.OverwriteFile,
        )
    else:
        confirm = hou.ui.displayConfirmation(
            "Clear the stroke file cache on disk?",
            suppress=hou.confirmType.OverwriteFile,
        )

    if confirm:
        filepath_eval(node)

        geopath = node.parm(get_fpe_name(node)).evalAsString()
        geopath = hou.text.normpath(geopath)
        geopath = hou.text.abspath(geopath)

        isogrp_toggle = node.parm(get_actiontoggle_name(node)).evalAsInt()
        isogrp_query = node.parm(get_actiongrp_name(node)).evalAsString()

        if os.path.exists(geopath):
            # overwrite the disk file with a blank hou geo

            c_geo = hou.Geometry()
            clear_geo_attribs(c_geo)

            if isogrp_toggle:
                c_geo.loadFromFile(geopath)
                del_groups = find_multi_groups(c_geo, isogrp_query)
                c_geo = isolate_multigroups_v2(c_geo, del_groups)

            try:
                c_geo.saveToFile(str(geopath))
                # load new saved cached into disk cache data parm
                update_filecache(node)
            except hou.OperationFailed:
                hou.ui.displayMessage("Hpaint: Failed to overwrite disk file")
    node.parm("hp_file_reload").pressButton()


def swap_file_into_buffer(node: hou.Node):
    """
    Take the pathed disk geo and delete it, placing it into the stroke buffer.
    This makes the disk file editable, and is essentially swapping between the uneditable 'file data parm'
    to the 'buffer data parm'
    """

    isogrp_toggle = node.parm(get_actiontoggle_name(node)).evalAsInt()
    isogrp_query = node.parm(get_actiongrp_name(node)).evalAsString()

    if isogrp_toggle:
        confirm = hou.ui.displayConfirmation(
            "Swap disk file group into stroke buffer?\nThis will remove any strokes in your current disk file (matching the group pattern {0}) and place them into the stroke buffer.".format(
                isogrp_query
            ),
            suppress=hou.confirmType.OverwriteFile,
        )
    else:
        confirm = hou.ui.displayConfirmation(
            "Swap disk file into stroke buffer?\nThis will remove any strokes in your current disk file and place them into the stroke buffer.",
            suppress=hou.confirmType.OverwriteFile,
        )

    if confirm:
        filepath_eval(node)

        diskcache_path = node.parm(get_fpe_name(node)).evalAsString()
        diskcache_path = hou.text.normpath(diskcache_path)
        diskcache_path = hou.text.abspath(diskcache_path)

        diskcache_geo = hou.Geometry()
        clear_geo_attribs(diskcache_geo)

        if os.path.exists(diskcache_path):
            try:
                diskcache_geo.loadFromFile(diskcache_path)
            except hou.OperationFailed:
                return
            # save a blank geo to the pathed disk file
            # if it fails, return and do not update the buffer
            resaved_geo = hou.Geometry()
            clear_geo_attribs(resaved_geo)
            if isogrp_toggle:
                resaved_geo.merge(diskcache_geo)
                del_groups = find_multi_groups(resaved_geo, isogrp_query)
                resaved_geo = isolate_multigroups_v2(resaved_geo, del_groups)
            try:
                resaved_geo.saveToFile(str(diskcache_path))
            except hou.OperationFailed:
                hou.ui.displayMessage("Hpaint: Failed to overwrite disk file")
                return
            # load new saved cached into disk cache data parm
            with hou.undos.disabler():
                update_filecache(node)

        strokecache_parm = node.parm(get_strokecache_name(node))

        strokecache_geo = strokecache_parm.evalAsGeometry()

        new_sc_geo = hou.Geometry()
        clear_geo_attribs(new_sc_geo)
        new_sc_geo.merge(strokecache_geo)

        if isogrp_toggle:
            del_groups = find_multi_groups(diskcache_geo, isogrp_query)
            isolate_dc_geo = isolate_multigroups_v2(
                diskcache_geo, del_groups, inverse=True
            )
            new_sc_geo.merge(isolate_dc_geo)
        else:
            new_sc_geo.merge(diskcache_geo)

        # set finally returned swap geo
        with hou.undos.disabler():
            strokecache_parm.set(new_sc_geo)


def update_filecache(node: hou.Node):
    """
    Push the disk file to the disk file read python SOP
    """

    filepath_eval(node)

    diskcache_geo = hou.Geometry()
    clear_geo_attribs(diskcache_geo)
    diskcache_path = node.parm(get_fpe_name(node)).evalAsString()
    try:
        diskcache_geo.loadFromFile(diskcache_path)
    except hou.OperationFailed:
        pass

    clear_geo_groups(diskcache_geo)

    with hou.undos.disabler():
        node.parm(get_filecache_name(node)).set(diskcache_geo)


def get_filecache_geo(node: hou.Node):
    """
    Try to load the file cache on disk
    """

    filepath_eval(node)

    diskcache_geo = hou.Geometry()
    clear_geo_attribs(diskcache_geo)
    diskcache_path = node.parm(get_fpe_name(node)).evalAsString()
    try:
        diskcache_geo.loadFromFile(diskcache_path)
        clear_geo_groups(diskcache_geo)
        return diskcache_geo
    except hou.OperationFailed:
        return None


def set_global_attrib(input_geo: hou.Geometry, attrib_name: str, value, default_value):
    """
    Set a global (detail) attrib
    """
    if input_geo.findGlobalAttrib(attrib_name) is None:
        input_geo.addAttrib(hou.attribType.Global, attrib_name, default_value)
    input_geo.setGlobalAttribValue(attrib_name, value)


def find_multi_groups(geometry: hou.Geometry, query: str):
    """Added for use with 'action by group' parm. Finds all groups
    that match the input file pattern and returns primGroup tuple

    """
    groups_tuple = geometry.primGroups()

    group_names = []

    for group in groups_tuple:
        group_names.append(group.name())

    reg_strokegroups = fnmatch.filter(group_names, query)

    query_delgroups = []

    if reg_strokegroups is not None:
        for strokegroup_name in reg_strokegroups:
            del_grp = geometry.findPrimGroup(strokegroup_name)
            if not del_grp:
                continue
            query_delgroups.append(del_grp)

    return query_delgroups


def isolate_multigroups(geometry, groups):
    """Given input geometry and primGroup list, delete eligible prims."""
    cache_geometry = hou.Geometry()
    clear_geo_attribs(cache_geometry)
    cache_geometry.merge(geometry)

    for group in groups:
        if cache_geometry is not None:
            group_prims = group.prims()
            cache_geometry.deletePrims(group_prims)

    return cache_geometry


def isolate_multigroups_v2(
    geometry: hou.Geometry,
    groups: typing.Union[tuple, hou.PrimGroup],
    inverse: bool = False,
):
    if not inverse:
        group_globstring = " ".join(group.name() for group in groups)
    else:
        group_globstring = " !".join(group.name() for group in groups)
        group_globstring = f"!{group_globstring}"

    cache_geometry = hou.Geometry()
    clear_geo_attribs(cache_geometry)
    cache_geometry.merge(geometry)

    glob_prims = cache_geometry.globPrims(group_globstring)

    cache_geometry.deletePrims(glob_prims)

    return cache_geometry


def isolate_multigroups_inverse(geometry, groups):
    """Same as isolate_multigroups, but deletes any prims NOT in group list."""
    cache_geometry = hou.Geometry()
    clear_geo_attribs(cache_geometry)
    cache_geometry.merge(geometry)

    iso_prims = []

    for group in groups:
        if cache_geometry is not None:
            group_prims = group.prims()

            for prim in group_prims:
                if prim not in iso_prims:
                    iso_prims.append(prim)

    inverse_prims = [p for p in geometry.prims()]

    for iso_prim in iso_prims:
        if iso_prim in inverse_prims:
            inverse_prims.remove(iso_prim)

    cache_geometry.deletePrims(inverse_prims)

    return cache_geometry


def filepath_eval(node):
    """Refresh the invisible file path with an absolute version, adhering to
    the way that animation is evaluated
    """

    fpe_toggle = node.parm("hp_enable_llf").evalAsInt()

    geopath_parm = node.parm(get_filepath_name(node))
    evalparm = node.parm(get_fpe_name(node))

    if geopath_parm.isTimeDependent() and fpe_toggle:
        geopath_expr = geopath_parm.rawValue()

        fpe_type = node.parm("hp_near_method").evalAsInt()

        with hou.undos.disabler():
            geopath_abs = time_snap_expr(geopath_expr, fpe_type)
            evalparm.set(geopath_abs)

    else:
        geopath_abs = geopath_parm.evalAsString()

        with hou.undos.disabler():
            evalparm.set(geopath_abs)


def walk_time_expr(geopath_expr):
    """Walk the length of the file path string to evaluate $F (accounting
    for frame padding)
    I couldn't think of a better way to do this...
    Please let me know if there is!!!
    """

    padded_hsex = "$F"

    framex_cindex = -1

    exrange_begin = -1
    exrange_end = -1

    for i, v in enumerate(geopath_expr):
        if v == "$" and len(geopath_expr) >= i + 1:
            if geopath_expr[i + 1] == "F":
                framex_cindex = i + 2

                exrange_begin = i
                break

    for i in range(framex_cindex, len(geopath_expr)):
        eval_character = geopath_expr[i]
        if eval_character.isdigit():
            padded_hsex += eval_character
        else:
            exrange_end = i
            break

    return padded_hsex, exrange_begin, exrange_end


def time_snap_expr(geopath_expr, fpe_type):
    """Given a raw file path expression in houdini (including $F)
    snap to the condition given (0 = back 1 = forward)

    """
    geopath_abs = hou.expandString(geopath_expr)

    padded_hsex, exrange_begin, exrange_end = walk_time_expr(geopath_expr)

    geopath_query = hou.expandString(geopath_expr.replace(padded_hsex, "*"))

    path_candidates = glob.glob(geopath_query)

    if len(path_candidates) == 0:
        return geopath_abs
    else:
        paths_corrected = [path.replace(os.sep, "/") for path in path_candidates]

        geopath_res = geopath_abs.replace(os.sep, "/")

        abspath_back = geopath_res

        if geopath_res not in paths_corrected:
            paths_corrected.append(geopath_res)

            # natural sort to return human visibility accounting for $F
            paths_corrected = natural_sort(paths_corrected)

            current_index = paths_corrected.index(geopath_res)

            if fpe_type == 0 and current_index - 1 >= 0:
                abspath_back = paths_corrected[current_index - 1]

            elif fpe_type == 1 and current_index + 1 < len(paths_corrected):
                abspath_back = paths_corrected[current_index + 1]

        return abspath_back


def set_ghost(node, condition):
    """Toggle the ghosting of visualised non-save frames"""
    ghost_switch_parm = node.node("ghost_switch").parm("input")

    with hou.undos.disabler():
        ghost_switch_parm.set(condition)
        ghost_switch_parm.pressButton()

    return


def natural_sort(list_to_sort):
    """
    Use natural sorting to ensure human (windows) list sort.
    See: https://blog.codinghorror.com/sorting-for-humans-natural-sort-order/
    """

    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def alphanum_key(key):
        return [convert(c) for c in re.split("([0-9]+)", key)]

    return sorted(list_to_sort, key=alphanum_key)


def get_strokecache_name(node):
    """Get the name of the stroke cache parm"""
    return "hp_strokecache"


def get_filecache_name(node):
    """Get the name of the file cache dir/name"""
    return "hp_filecache"


def get_filepath_name(node):
    """Get the name of the file path dir/name"""
    return "hp_file_path"


def get_fpe_name(node):
    """Get the name of the buffered (callback evaluation) file path dir/name"""
    return "hp_fpeval"


def get_actiontoggle_name(node):
    """Get the name of the 'action by group' toggle parm name"""
    return "hp_grp_iso"


def get_actiongrp_name(node):
    """Get the name of the 'action by group' name parm name"""
    return "hp_isogrp_name"
