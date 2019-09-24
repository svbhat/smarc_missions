# Christopher Iliffe Sprague
# sprague@kth.se
# Behaviours to use within a behaviour tree.
# https://arxiv.org/abs/1811.00426

import py_trees as pt, py_trees_ros as ptr, itertools, std_msgs.msg, copy, json, rospy, numpy as np
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from geodesy.utm import fromLatLong, UTMPoint
from sensor_msgs.msg import NavSatFix
import actionlib_msgs.msg as actionlib_msgs

import rospy
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Pose, Point, Quaternion, PoseStamped

class Sequence(pt.composites.Selector):

    """
    Reactive sequence overidding sequence with memory, py_trees' only available sequence.
    """

    def __init__(self, name="Sequence", children=None):
        super(Sequence, self).__init__(name=name, children=children)

    def tick(self):
        """
        Run the tick behaviour for this selector. Note that the status
        of the tick is always determined by its children, not
        by the user customised update function.
        Yields:
            :class:`~py_trees.behaviour.Behaviour`: a reference to itself or one of its children
        """
        self.logger.debug("%s.tick()" % self.__class__.__name__)
        # Required behaviour for *all* behaviours and composites is
        # for tick() to check if it isn't running and initialise
        if self.status != pt.common.Status.RUNNING:
            # selectors dont do anything specific on initialisation
            #   - the current child is managed by the update, never needs to be 'initialised'
            # run subclass (user) handles
            self.initialise()
        # run any work designated by a customised instance of this class
        self.update()
        previous = self.current_child
        for child in self.children:
            for node in child.tick():
                yield node
                if node is child:
                    if node.status == pt.common.Status.RUNNING or node.status == pt.common.Status.FAILURE:
                        self.current_child = child
                        self.status = node.status
                        if previous is None or previous != self.current_child:
                            # we interrupted, invalidate everything at a lower priority
                            passed = False
                            for child in self.children:
                                if passed:
                                    if child.status != pt.common.Status.INVALID:
                                        child.stop(pt.common.Status.INVALID)
                                passed = True if child == self.current_child else passed
                        yield self
                        return
        # all children succeded, set succed ourselves and current child to the last bugger who failed us
        self.status = pt.common.Status.SUCCESS
        try:
            self.current_child = self.children[-1]
        except IndexError:
            self.current_child = None
        yield self

class SetBlackboardVariable(pt.behaviours.Running):
    """
    Set the specified variable on the blackboard.
    Usually we set variables from inside other behaviours, but can
    be convenient to set them from a behaviour of their own sometimes so you
    don't get blackboard logic mixed up with more atomic behaviours.
    Args:
        name (:obj:`str`): name of the behaviour
        variable_name (:obj:`str`): name of the variable to set
        variable_value (:obj:`any`): value of the variable to set
    .. todo:: overwrite option, leading to possible failure/success logic.
    """
    def __init__(self,
                 name="Set Blackboard Variable",
                 variable_name="dummy",
                 variable_value=None
                 ):
        """
        :param name: name of the behaviour
        :param variable_name: name of the variable to set
        :param value_name: value of the variable to set
        """
        super(SetBlackboardVariable, self).__init__(name)
        self.variable_name = variable_name
        self.variable_value = variable_value

    def initialise(self):
        self.blackboard = pt.blackboard.Blackboard()
        self.blackboard.set(self.variable_name, self.variable_value, overwrite=True)

class Counter(pt.behaviour.Behaviour):

    # A simple counter

    def __init__(self, n, name='Counter', reset=False):

        # count
        self.i = 0
        self.n = n

        # resetting
        self.reset = reset

        # become a behaviour
        super(Counter, self).__init__(name)

    def update(self):

        # increment the count
        self.i += 1

        # react to the result
        return pt.common.Status.FAILURE if self.i <= self.n else pt.common.Status.SUCCESS

    def terminate(self, status):
        self.i = 0 if status == pt.common.Status.SUCCESS and self.reset else self.i

class SetNextWaypoint(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard access
        self.bb = pt.blackboard.Blackboard()

        # become behaviour
        pt.behaviour.Behaviour.__init__(self, "Set next waypoint")

    def update(self):

        # set current waypoint to the next one
        self.bb.set("waypoint_i", self.bb.get("waypoint_i") + 1)
        return pt.common.Status.RUNNING

class AtFinalWaypoint(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard access
        self.bb = pt.blackboard.Blackboard()

        # become behaviour
        pt.behaviour.Behaviour.__init__(self, "At final waypoint?")

    def update(self):

        # current status
        i = self.bb.get("waypoint_i")
        n = self.bb.get("n_waypoints")
        self.feedback_message = "Waypoint {} of {}".format(i, n)

        # react to result
        return pt.common.Status.SUCCESS if i == n else pt.common.Status.FAILURE
            
class GoTo(pt.behaviour.Behaviour):

    """
    Publishes to relevant topics while preconditions are met.
    NOTE: basic publishing until go to action server is available
    """

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # publishers
        self.pitch = rospy.Publisher(
            '/pitch_setpoint',
            std_msgs.msg.Float64,
            queue_size=100
        )
        self.depth = rospy.Publisher(
            '/depth_setpoint',
            std_msgs.msg.Float64,
            queue_size=100
        )

        # become a behaviour
        super(GoTo, self).__init__("Go to waypoint!")

    def update(self):
        
        # current waypoint
        i = self.bb.get("goal_waypoint")

        # pitch and depth goals
        pitch = float(self.bb.get('plan')[i]['data']['pitch'])
        depth = float(self.bb.get('plan')[i]['data']['z'])

        # publish
        self.pitch.publish(std_msgs.msg.Float64(pitch))
        self.depth.publish(std_msgs.msg.Float64(depth))

        # feedback
        self.feedback_message = "Waypoint {} | pitch={}, depth={}".format(i, pitch, depth)

        # always running if preconditions are met
        return pt.common.Status.RUNNING

class SynchroniseMission(ptr.subscribers.Handler):

    '''
    - Returns running until /plan_db recieves a 
    message.
    - Set's the plan and the number of waypoints, 
    returning success after /plan_db recieves a
    message.
    - Returns success indefinitely thereafter.
    '''

    def __init__(self, plan_tpc='/plan_db'):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # plan iteration
        self.pi = 0

        # become a behaviour
        super(SynchroniseMission, self).__init__(
            name="Synchronise mission!",
            topic_name=plan_tpc,
            topic_type=std_msgs.msg.String,
            clearing_policy=pt.common.ClearingPolicy.ON_SUCCESS
        )
        
        # create a markerArray publisher - ozer
        # TODO change topic
        self.marker_array_pub = rospy.Publisher('/rviz_marker_array', MarkerArray, queue_size=1)
        self.marker_array = MarkerArray()

    def update(self):

        with self.data_guard:

            # if there isn't a message and we don't have a plan yet
            if (self.msg ==  None or len(str(self.msg)) < 135) and self.bb.get('plan') == None:
                self.feedback_message = "Waiting for a plan"
                return pt.common.Status.RUNNING

            # recieved plan
            if isinstance(self.msg, std_msgs.msg.String) and len(str(self.msg)) > 135:

                # incremenet plan number
                self.pi += 1

                # feedback message
                self.feedback_message = "Recieved new plan {}".format(self.pi)

                # get the plan and utm zone from neptus
                plan, zone, band = self.clean(self.msg)

                # set the blackboard variables
                self.bb.set("plan", plan)
                self.bb.set("n_waypoints", len(plan))
                self.bb.set("waypoint_i", 0)
                self.bb.set("utmzone", zone)
                self.bb.set("band", band)
                
                #also publish the points into for rviz - ozer's stuff
                for i, ptn in enumerate(plan):
                    marker = Marker()
                    marker.ns = '/marker_array'
                    marker.id = i
                    marker.action = 0
                    marker.type = 3 #cylinder
                    pose = Pose()
                    pose.position.x = ptn[0]
                    pose.position.y = ptn[1]
                    pose.position.z = ptn[2]
                    pose.orientation.w = 1
                    marker.pose = pose
                    marker.scale.x = 1.0
                    marker.scale.y = 1.0
                    marker.scale.z = 1.0
                    # a, rgb in [0,1]
                    marker.color.a = 1
                    marker.color.r = 1
                    marker.color.g = 0
                    marker.color.b = 1
                    marker.header.frame_id = '/world'
                    self.marker_array.markers.append(marker)
                self.marker_array_pub.publish(self.marker_array)

                # clear the message so it goes to else unless new message is recieved.
                self.msg = None
                return pt.common.Status.SUCCESS

            # otherwise
            else:
                self.feedback_message = "Using plan {}".format(self.pi)
                return pt.common.Status.SUCCESS      

    @staticmethod
    def clean(f):

        f = str(f)
        # clean the neptus message
        f = f.replace(' ', '')
        f = f.replace('\\n', '')
        f = f.replace('\\"', '"')
        f = f.replace('"\\', '"')
        f = f.replace('\\', '')
        f = f.split(',"transitions":')[0]
        f = f.split('"maneuvers":')[1]
        f = f.replace('\n', '')
        f = f.split(',"transitions"')[0]

        # convert to json
        f = json.loads(f)

        # convert lat lon to utm
        depths = [float(d['data']['z']) for d in f]

        # ensure signs of depths
        depths = [-d if d > 0 else d for d in depths]

        # get latitute and longitude
        f = [fromLatLong(np.degrees(float(d['data']['lat'])), np.degrees(float(d['data']['lon']))) for d in f]

        # get the grid-zone
        gz, band = f[0].gridZone()

        # convert utm to point
        f = [d.toPoint() for d in f]

        # convert point to xyz
        f = [(d.x, d.y, depth) for d, depth in zip(f, depths)]

        # return list of utm xyz waypoints and the utm zone
        return f, gz, band

class Safe(ptr.subscribers.Handler):

    '''
    Returns success as long as there is not
    any message recieved at /abort.
    '''

    def __init__(self):

        # become a behaviour
        super(Safe, self).__init__(
            name="Safe?",
            topic_name="/abort",
            topic_type=std_msgs.msg.Empty
        )

    def update(self):

        # do not abort
        if self.msg == None:
            self.feedback_message = "Everything is okay"
            return pt.common.Status.SUCCESS
        
        # abort
        else:
            self.feedback_message = "Mission aborted!"
            return pt.common.Status.FAILURE

class GoToWayPoint(ptr.actions.ActionClient):

    def __init__(self):

        # blackboard access
        self.bb = pt.blackboard.Blackboard()

        # become action client
        ptr.actions.ActionClient.__init__(
            self,
            name="Go to waypoint",
            action_spec=MoveBaseAction,
            action_goal=None,
            action_namespace="/bezier_planner",
            override_feedback_message_on_running="Moving to waypoint"
        )

        # publish back to neptus
        self.neptus = rospy.Publisher('/lolo_auv_1/estimated_state', NavSatFix, queue_size=1)

    def initialise(self):

        # get waypoint
        i = self.bb.get("waypoint_i")
        wp = self.bb.get("plan")[i]

        # construct the message
        self.action_goal = MoveBaseGoal()
        self.action_goal.target_pose.pose.position.x = wp[0]
        self.action_goal.target_pose.pose.position.y = wp[1]
        self.action_goal.target_pose.pose.position.z = wp[2]

        self.sent_goal = False

    def update(self):

        """
        Check only to see whether the underlying action server has
        succeeded, is running, or has cancelled/aborted for some reason and
        map these to the usual behaviour return states.
        """

        self.logger.debug("{0}.update()".format(self.__class__.__name__))

        # if your action client is not valid
        if not self.action_client:
            self.feedback_message = "no action client, did you call setup() on your tree?"
            return pt.Status.INVALID

        # if goal hasn't been sent yet
        if not self.sent_goal:
            self.action_client.send_goal(self.action_goal, feedback_cb=self.feedback_cb)
            self.sent_goal = True
            self.feedback_message = "sent goal to the action server"
            return pt.Status.RUNNING
        self.feedback_message = self.action_client.get_goal_status_text()

        # if the goal was aborted or preempted
        if self.action_client.get_state() in [actionlib_msgs.GoalStatus.ABORTED,
                                              actionlib_msgs.GoalStatus.PREEMPTED]:
            return pt.Status.FAILURE
        result = self.action_client.get_result()

        # if the goal was accomplished
        if result:
            return pt.Status.SUCCESS

        # if we're still trying to accomplish the goal
        else:

            # a nice little message :) xoxo
            self.feedback_message = self.override_feedback_message_on_running

            return pt.Status.RUNNING

    def feedback_cb(self, msg):

        # get positional feedback of the p2p goal
        msg = msg.base_position.pose.position

        # get the utm zone
        utmz = self.bb.get('utmzone')

        # get band zone
        band = self.bb.get("band")

        # make utm point
        pnt = UTMPoint(easting=msg.x, northing=msg.y, altitude=0, zone=utmz, band=band)

        # get lat-lon
        pnt = pnt.toMsg()

        # construct message for neptus
        msg = NavSatFix()
        msg.latitude = np.radians(pnt.latitude)
        msg.longitude = np.radians(pnt.longitude)

        # send the message to neptus
        self.neptus.publish(msg)

"""
class DataPublisher(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # initialise the blackboard
        self.bb.set("ready", 0)
        self.bb.set("initialising", 0)
        self.bb.set("executing", 0)

        # topic
        self.pub = rospy.Publisher(
            '/plan_cotrol_state',
            imc_ros_bridge.msg.PlanControl,
            queue_size=100
        )

        # become behaviour
        super(DataPublisher, self).__init__("Data publisher")

    def update(self):

        # instantiate message
        msg = imc_ros_bridge.msg.PlanControl()

        # add relevant things from blackboard
        msg.READY = std_msgs.msg.UInt8(self.bb.get("ready"))
        msg.INITIALIZING = std_msgs.msg.UInt8(self.bb.get("initialising"))
        msg.EXECUTING = std_msgs.msg.UInt8(self.bb.get("executing"))

        # NOTE: add more to message

        # publish it!
        self.pub.publish(msg)

        return pt.common.Status.RUNNING

"""
