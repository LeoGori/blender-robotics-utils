# Copyright (C) 2006-2021 Istituto Italiano di Tecnologia (IIT)
# All rights reserved.
#
# This software may be modified and distributed under the terms of the
# BSD-3-Clause license. See the accompanying LICENSE file for details.

from ntpath import join
import bpy
import os
# import sys
import yarp
import idyntree.bindings as iDynTree
# import numpy as np
import math
import json
from .common_functions import (printError,
                               look_for_bones_with_drivers,
                               bones_with_driver,
                               IkVariables as ikv,
                               InverseKinematics,
                               )

from bpy_extras.io_utils import ImportHelper
from bpy_extras import view3d_utils

from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       FloatProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       PointerProperty,
                       CollectionProperty
                       )
from bpy.types import (Panel,
                       Menu,
                       Operator,
                       PropertyGroup,
                       UIList
                       )

list_of_links = []

global robot_name
robot_name = "R1Mk3" # R1SN003 or iCub or R1Mk3

# ------------------------------------------------------------------------
#    Structures
# ------------------------------------------------------------------------

class rcb_wrapper():
    def __init__(self, driver, icm, iposDir, ipos, ienc, encs, iax, joint_limits):
        self.driver = driver
        self.icm = icm
        self.iposDir = iposDir
        self.ipos = ipos
        self.ienc = ienc
        self.encs = encs
        self.iax = iax
        self.joint_limits = joint_limits


# ------------------------------------------------------------------------
#    Operators
# ------------------------------------------------------------------------
def register_rcb(rcb_instance, rcb_name):
    scene = bpy.types.Scene
    scene.rcb_wrapper[rcb_name] = rcb_instance


def unregister_rcb(rcb_name):
    try:
        del bpy.types.Scene.rcb_wrapper[rcb_name]
    except:
        pass


def move(dummy):
    threshold = 10.0 # degrees
    scene = bpy.types.Scene
    mytool = bpy.context.scene.my_tool
    for key in scene.rcb_wrapper:
        rcb_instance = scene.rcb_wrapper[key]
        # Get the handles
        icm     = rcb_instance.icm
        iposDir = rcb_instance.iposDir
        ipos    = rcb_instance.ipos
        ienc    = rcb_instance.ienc
        encs    = rcb_instance.encs
        iax     = rcb_instance.iax
        joint_limits     = rcb_instance.joint_limits
        # Get the targets from the rig
        ok_enc = ienc.getEncoders(encs.data())
        if not ok_enc:
            print("I cannot read the encoders, skipping")
            return

        for joint in range(0, ipos.getAxes()):
            # TODO handle the name of the armature, just keep robot_name for now
            joint_name = iax.getAxisName(joint)
            if joint_name not in bpy.data.objects[mytool.my_armature].pose.bones.keys():
                print(f"Skipping the motion of the requested joint {joint_name} because it is not present in the armature of the model.")
                print("May have you mispelled the name? Check the joint tag names in the .urdf file, or the names of the bones in the .blend file of the model")
                continue

            target = math.degrees(bpy.data.objects[mytool.my_armature].pose.bones[joint_name].rotation_euler[1])
            min    = joint_limits[joint][0]
            max    = joint_limits[joint][1]
            # if max < min:
            #     new_max = min
            #     min = max
            #     max = new_max
            # print(annotations)
            # if target < min or target > max:
            #     print("The target", target, "for joint", joint_name,"is outside the boundaries (", min, ",", max, "), skipping.")
            #     continue

            safety_check=None
            # The R1SN003 hands encoders are not reliable for the safety check.
            # if mytool.my_armature == robot_name and joint > 5 :
            #     safety_check = False
            # else:
            #     safety_check = (abs(encs[joint] - target) > threshold)

            safety_check = False

            if safety_check:
                print("The target is too far, reaching in position control, for joint", joint_name, "by ", abs(encs[joint] - target), " degrees" )

                # Pause the animation
                bpy.ops.screen.animation_play() # We have to check if it is ok
                # Switch to position control and move to the target
                # TODO try to find a way to use the s methods
                icm.setControlMode(joint, yarp.VOCAB_CM_POSITION)
                ipos.setRefSpeed(joint,10)
                ipos.positionMove(joint,target)
                done = ipos.isMotionDone(joint)
                while not done:
                    done = ipos.isMotionDone(joint)
                    yarp.delay(0.001)
                # Once finished put the joints in position direct and replay the animation back
                icm.setControlMode(joint, yarp.VOCAB_CM_POSITION_DIRECT)
                bpy.ops.screen.animation_play()
            else:
                print(f"move() has been called, moving joint {joint_name} to target {target}")
                iposDir.setPosition(joint,target)


def float_callback(self, context):
    # Callback for sliders. Find each object in the links dictionary and set its rotation.
    try:
        joint_tool = context.scene.my_joints
        pose_bones = bpy.data.objects[bpy.context.scene.my_tool.my_armature].pose.bones
        for joint_name, joint_value in joint_tool.items():
            joint = pose_bones[joint_name]
            # It is a prismatic joint (to be tested)
            if joint.lock_rotation[1]:
                joint.delta_location[1] = joint_value
            # It is a revolute joint
            else:
                joint.rotation_euler[1] = joint_value * math.pi / 180.0
                joint.keyframe_insert(data_path="rotation_euler")

    except AttributeError:
        pass


class AllJoints:

    def __init__(self):
        self.annotations = {}
        self.joint_names = []
        self.generate_joint_classes()

    def generate_joint_classes(self):

        self.joint_names = bpy.data.objects[bpy.context.scene.my_tool.my_armature].pose.bones.keys()

        for joint_name, joint in bpy.data.objects[bpy.context.scene.my_tool.my_armature].pose.bones.items():

            # Our bones rotate around y (revolute joint), translate along y (prismatic joint), if both are locked, it
            # means it is a fixed joint.
            if joint.lock_rotation[1] and joint.lock_location[1]:
                continue

            joint_min = -360
            joint_max =  360

            rot_constraint = None
            for constraint in joint.constraints:
                if constraint.type == "LIMIT_ROTATION":
                    rot_constraint = constraint
                    break
            if rot_constraint is not None:
                joint_min = rot_constraint.min_y * 180 / math.pi
                joint_max = rot_constraint.max_y * 180 / math.pi

            self.annotations[joint_name] = FloatProperty(
                name=joint_name,
                description=joint_name,
                default=0,
                min=joint_min,
                max=joint_max,
                update=float_callback,
            )


# ------------------------------------------------------------------------
#    Scene Properties
# ------------------------------------------------------------------------

def getLinks(self, context):
    return list_of_links

class MyProperties(PropertyGroup):

    my_bool: BoolProperty(
        name="Dry run",
        description="If ticked, the movement will not replayed",
        default=False
        )

    my_int: IntProperty(
        name="Int Value",
        description="A integer property",
        default=23,
        min=10,
        max=100
        )

    my_float: FloatProperty(
        name="Threshold(degrees)",
        description="Threshold for the safety checks",
        default=5.0,
        min=2.0,
        max=15.0
        )

    my_float_vector: FloatVectorProperty(
        name="Float Vector Value",
        description="Something",
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=0.1
    )

    my_string: StringProperty(
        name="Robot",
        description=":",
        default=robot_name,
        maxlen=1024,
        )

    my_armature: StringProperty(
        name="Armature name",
        description=":",
        default=robot_name,
        maxlen=1024,
        )

    my_path: StringProperty(
        name="Directory",
        description="Choose a directory:",
        default="",
        maxlen=1024,
        subtype='DIR_PATH'
        )

    my_reach_x: FloatProperty(
        name="X",
        description="The target along x axis",
        default=0.0,
        min = -100.0,
        max = 100.0
        )

    my_reach_y: FloatProperty(
        name="Y",
        description="The target along y axis",
        default=0.0,
        min=-100.0,
        max=100.0
        )

    my_reach_z: FloatProperty(
        name="Z",
        description="The target along z axis",
        default=0.0,
        min=-100.0,
        max=100.0
        )

    my_reach_pitch: FloatProperty(
        name="Pitch",
        description="The target around Pitch",
        default=0.0,
        min=-360.0,
        max=360.0
        )

    my_reach_yaw: FloatProperty(
        name="Yaw",
        description="The target around Yaw",
        default=0.0,
        min=-360.0,
        max=360.0
        )

    my_reach_roll: FloatProperty(
        name="Roll",
        description="The target around Roll",
        default=0.0,
        min=-360.0,
        max=360.0
        )

    my_baseframeenum: EnumProperty(
        name="Base frame name:",
        description="Select the base frame:",
        items=getLinks
        )
    my_eeframeenum: EnumProperty(
        name="End-effector frame name:",
        description="Select the end-effector frame:",
        items=getLinks
        )


class ListItem(PropertyGroup):
    value: StringProperty(
           name="Name",
           description="A name for this item",
           default="Untitled")

    viewValue: StringProperty(
           name="Displayed Name",
           description="",
           default="")

    isConnected: BoolProperty(
        name="",
        default = False
    )


class MY_UL_List(UIList):

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        if (item.isConnected):
            custom_icon = 'LINKED'
        else:
            custom_icon = 'UNLINKED'

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.viewValue, icon = custom_icon)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text=item.viewValue, icon = custom_icon)


class WM_OT_Disconnect(bpy.types.Operator):
    bl_label = "Disconnect"
    bl_idname = "wm.disconnect"
    bl_description= "disconnect the selected part(s)"

    def execute(self, context):
        scene = bpy.context.scene
        parts = scene.my_list
        rcb_instance = bpy.types.Scene.rcb_wrapper[getattr(parts[scene.list_index], "value")]

        if rcb_instance is None:
            return {'CANCELLED'}
        rcb_instance.driver.close()

        del bpy.types.Scene.rcb_wrapper[getattr(parts[scene.list_index], "value")]

        setattr(parts[scene.list_index], "isConnected", False)

        return {'FINISHED'}


class WM_OT_Connect(bpy.types.Operator):
    bl_label = "Connect"
    bl_idname = "wm.connect"
    bl_description= "connect the selected part(s)"

    def execute(self, context):
        scene = bpy.context.scene
        parts = scene.my_list
        mytool = scene.my_tool

        yarp.Network.init()
        if not yarp.Network.checkNetwork():
            printError(self, "YARP server is not running!")
            return {'CANCELLED'}

        options = yarp.Property()
        driver = yarp.PolyDriver()

        # set the poly driver options
        options.put("robot", mytool.my_string)
        options.put("device", "remote_controlboard")
        print(f'local port: {"/blender_controller/client/"+getattr(parts[scene.list_index], "value")}')
        options.put("local", "/blender_controller/client/"+getattr(parts[scene.list_index], "value"))
        # print(f'remote port: {"/"+mytool.my_string+"/"+getattr(parts[scene.list_index], "value")}')
        # options.put("remote", "/"+mytool.my_string+"/"+getattr(parts[scene.list_index], "value"))
        print(f'remote port: {"/r1mk3Sim/"+getattr(parts[scene.list_index], "value")}')
        options.put("remote", "/r1mk3Sim/"+getattr(parts[scene.list_index], "value"))

        # opening the drivers
        print('Opening the motor driver...')
        driver.open(options)

        if not driver.isValid():
            printError(self, "Cannot open the driver!")
            return {'CANCELLED'}

        # opening the drivers
        print('Viewing motor position/encoders...')
        icm = driver.viewIControlMode()
        iposDir = driver.viewIPositionDirect()
        ipos = driver.viewIPositionControl()
        ienc = driver.viewIEncoders()
        iax = driver.viewIAxisInfo()
        ilim = driver.viewIControlLimits()
        if ienc is None or ipos is None or icm is None or iposDir is None or iax is None or ilim is None:
            printError(self, "Cannot view one of the interfaces!")
            return {'CANCELLED'}

        encs = yarp.Vector(ipos.getAxes())
        joint_limits = []

        for joint in range(0, ipos.getAxes()):
            min = yarp.Vector(1)
            max = yarp.Vector(1)
            icm.setControlMode(joint, yarp.VOCAB_CM_POSITION_DIRECT)
            ilim.getLimits(joint, min.data(), max.data())
            joint_limits.append([min.get(0), max.get(0)])

        register_rcb(rcb_wrapper(driver, icm, iposDir, ipos, ienc, encs, iax, joint_limits), getattr(parts[scene.list_index], "value"))

        setattr(parts[scene.list_index], "isConnected", True)

        # TODO check if we need this
        #bpy.app.handlers.frame_change_post.clear()
        #bpy.app.handlers.frame_change_post.append(move)

        return {'FINISHED'}


class WM_OT_Configure(bpy.types.Operator):
    bl_label = "Configure"
    bl_idname = "wm.configure"
    bl_description= "configure the parts by uploading a configuration file (.json format)"

    def execute(self, context):
        scene = bpy.context.scene
        mytool = scene.my_tool

        bpy.ops.rcb_panel.open_filebrowser('INVOKE_DEFAULT')

        try:
            # init the callback
            bpy.app.handlers.frame_change_post.append(move)
        except:
            printError(self, "A problem when initialising the callback")

        robot = AllJoints()

        # Dynamically create the same class
        JointProperties = type(
            # Class name
            "JointProperties",

            # Base class
            (bpy.types.PropertyGroup, ),
                {"__annotations__": robot.annotations},
        )

        # OBJECT_PT_robot_controller.set_joint_names(my_list)
        bpy.utils.register_class(JointProperties)
        bpy.types.Scene.my_joints = PointerProperty(type=JointProperties)

        return {'FINISHED'}


class WM_OT_ReachTarget(bpy.types.Operator):
    bl_label = "Reach Target"
    bl_idname = "wm.reach_target"

    bl_description = "Reach the cartesian target"

    def execute(self, context):
        return InverseKinematics.execute(self)


class WM_OT_initiate_drag_drop(bpy.types.Operator):
    """Process input while Control key is pressed"""
    bl_idname = 'wm.initiate_drag_drop'
    bl_label = 'Drag & Drop'
    # bl_options = {'REGISTER'}

    def execute(self, context):
        print("Going to invoke the modal operator")
        bpy.ops.object.modal_operator('INVOKE_DEFAULT')
        return {'FINISHED'}

class ModalOperator(bpy.types.Operator):
    bl_idname = "object.modal_operator"
    bl_label = "Drap and Drop Operator"

    def __init__(self):
        print("Invoked!!!")
        self.mouse_pos = [0.0, 0.0]
        self.object = None
        self.loc_3d = [0.0, 0.0, 0.0]

    def __del__(self):
        print("End operator")

    def execute(self, context):
        print("location: ", self.loc_3d[0], self.loc_3d[1], self.loc_3d[2])
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE':  # Apply
            self.loc_3d = [event.mouse_region_x, event.mouse_region_y]

            self.object = bpy.context.object
            region = bpy.context.region
            region3D = bpy.context.space_data.region_3d
            #The direction indicated by the mouse position from the current view
            view_vector = view3d_utils.region_2d_to_vector_3d(region, region3D, self.loc_3d)
            #The 3D location in this direction
            self.loc_3d = view3d_utils.region_2d_to_location_3d(region, region3D, self.loc_3d, view_vector)
            #The 3D location converted in object local coordinates
            # self.loc_3d = self.object.matrix_world.inverted() * mouse_loc

            InverseKinematics.execute(self, self.loc_3d)

            self.execute(context)

        elif event.type == 'RIGHTMOUSE':  # Cancel
            print("Quit pressed")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            print("Drag and Drop operator invoked")
            args = (self, context)
            # self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, args, 'WINDOW', 'POST_PIXEL')

            # Keeps mouse position current 3D location and current object for the draw callback
            # (not needed to make self attribute if you don't want to use the callback)
            self.loc_3d = [0, 0, 0]

            self.object = context.object

            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

# ------------------------------------------------------------------------
#    Panel in Object Mode
# ------------------------------------------------------------------------

class OBJECT_PT_robot_controller(Panel):
    bl_label = "Robot controller"
    bl_idname = "OBJECT_PT_robot_controller"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tools"
    bl_context = "posemode"
    # joint_name = []

    # @classmethod
    # def poll(cls, context):
    #     return context.object is not None

    # @staticmethod
    # def set_joint_names(joint_names):
    #     OBJECT_PT_robot_controller.joint_names = joint_names

    def draw(self, context):

        if not bones_with_driver:
            look_for_bones_with_drivers(context.scene.my_tool.my_armature)

        if ikv.iDynTreeModel is None:
            configure_ik()

        layout = self.layout
        scene = context.scene
        parts = scene.my_list
        mytool = scene.my_tool
        rcb_wrapper = bpy.types.Scene.rcb_wrapper

        box_configure = layout.box()
        box_configure.prop(mytool, "my_armature")
        box_configure.operator("wm.configure")

        box = layout.box()
        box.label(text="Selection Tools")
        box.template_list("MY_UL_List", "The_List", scene,
                          "my_list", scene, "list_index")

        box.prop(mytool, "my_string")
        row_connect = box.row(align=True)
        row_connect.operator("wm.connect")
        layout.separator()
        row_disconnect = box.row(align=True)
        row_disconnect.operator("wm.disconnect")
        layout.separator()

        reach_box = layout.box()
        reach_box.label(text="Reach target")
        reach_box.row(align=True).prop(mytool, "my_baseframeenum")
        reach_box.row(align=True).prop(mytool, "my_eeframeenum")

        reach_box.label(text="Position")
        reach_box.row(align=True).prop(mytool, "my_reach_x")
        reach_box.row(align=True).prop(mytool, "my_reach_y")
        reach_box.row(align=True).prop(mytool, "my_reach_z")

        reach_box.label(text="Rotation")
        reach_box.row(align=True).prop(mytool, "my_reach_roll")
        reach_box.row(align=True).prop(mytool, "my_reach_pitch")
        reach_box.row(align=True).prop(mytool, "my_reach_yaw")
        reach_box.operator("wm.reach_target")

        reach_box.operator("wm.initiate_drag_drop")

        layout.separator()

        box_joints = layout.box()
        box_joints.label(text="joint angles")

        try:
            scene.my_joints
        except AttributeError:
            joints_exist = False
        else:
            joints_exist = True
            for joint_name, joint in bpy.data.objects[mytool.my_armature].pose.bones.items():
                # We do not have to add the entry in the list for the bones that have drivers
                # since they have not to be controlled directly, but throgh the driver.s
                if joint_name in bones_with_driver:
                    continue
                # Our bones rotate around y (revolute joint), translate along y (prismatic joint), if both are locked, it
                # means it is a fixed joint.
                if joint.lock_rotation[1] and joint.lock_location[1]:
                    continue
                box_joints.prop(scene.my_joints, joint_name)

        if len(context.scene.my_list) == 0 or not joints_exist:
            box.enabled = False
            box_configure.enabled = True
            box_joints.enabled = False
            reach_box.enabled = False
        else:
            box.enabled = True
            box_configure.enabled = False
            if bpy.context.screen.is_animation_playing:
                row_disconnect.enabled = False
                row_connect.enabled = False
                box_joints.enabled = False
                reach_box.enabled = False
            else:
                box_joints.enabled = True
                reach_box.enabled = ikv.configured
                if getattr(parts[scene.list_index], "value") in rcb_wrapper.keys():
                    row_disconnect.enabled = True
                    row_connect.enabled = False
                else:
                    row_disconnect.enabled = False
                    row_connect.enabled = True


class OT_OpenConfigurationFile(Operator, ImportHelper):

    bl_idname = "rcb_panel.open_filebrowser"
    bl_label = "Select the configuration file"

    filter_glob: StringProperty(
        default='*.json',
        options={'HIDDEN'}
    )

    def parse_conf(self, filepath, context):
        f = open(filepath)
        data = json.load(f)
        context.scene.my_list.clear()

        for p in data['parts']:
            item = context.scene.my_list.add()
            item.value = p[0]
            item.viewValue = p[1]

    def execute(self, context):
        filename, extension = os.path.splitext(self.filepath)
        self.parse_conf(self.filepath, context)
        # bpy.ops.object.process_input('INVOKE_DEFAULT')
        return {'FINISHED'}


def configure_ik():
    if 'model_urdf' not in bpy.context.scene:
        ikv.configured = False
        return
    ikv.configured = True
    model_urdf = bpy.context.scene['model_urdf']
    mdlLoader = iDynTree.ModelLoader()
    mdlLoader.loadModelFromString(model_urdf)
    ikv.iDynTreeModel = mdlLoader.model()

    # list_of_links = []
    for link_idx in range(ikv.iDynTreeModel.getNrOfLinks()):
        list_of_links.append((ikv.iDynTreeModel.getLinkName(link_idx),
                              ikv.iDynTreeModel.getLinkName(link_idx),
                              ""))

    ikv.inverseKinematics.setModel(ikv.iDynTreeModel)
    # Setup the ik problem
    ikv.inverseKinematics.setCostTolerance(0.0001)
    ikv.inverseKinematics.setConstraintsTolerance(0.00001)
    ikv.inverseKinematics.setDefaultTargetResolutionMode(iDynTree.InverseKinematicsTreatTargetAsConstraintNone)
    ikv.inverseKinematics.setRotationParametrization(iDynTree.InverseKinematicsRotationParametrizationRollPitchYaw)

    ikv.dynComp.loadRobotModel(ikv.iDynTreeModel)
    dofs = ikv.dynComp.model().getNrOfDOFs()
    s = iDynTree.VectorDynSize(dofs)
    for dof in range(dofs):
        s.setVal(dof, 0.0)
    ikv.dynComp.setJointPos(s)
