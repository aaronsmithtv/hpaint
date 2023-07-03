import hou

node = kwargs["node"]

# Set Colour
blue = hou.Color((0.6, 0.85, 0.98))
node.setColor(blue)

# Load initially pathed file
node.parm("hp_file_reload").pressButton()


# register python callback to be called on hip file event
# e.g loading, saving: for reloading hpaint cache
def hpaint_reload_se_callback(event_type):
    node.parm("hp_file_reload").pressButton()


with hou.undos.disabler():
    hou.hipFile.addEventCallback(hpaint_reload_se_callback)
