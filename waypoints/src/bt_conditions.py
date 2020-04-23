#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8



#TODO
# . C_HaveManualWaypoint
# . C_ManualWaypointReceived


from bt_common import *
from sam_globals import *
import py_trees as pt


class C_NoAbortReceived(pt.behaviour.Behaviour):
    def __init__(self):
        self.bb = pt.blackboard.Blackboard()
        self.aborted = False
        super(C_NoAbortReceived, self).__init__(name="C_NoAbortReceived")

    def update(self):
        if self.bb.get(ABORT_BB) or self.aborted:
            self.aborted = True
            return pt.Status.FAILURE
        else:
            return pt.Status.SUCCESS

class C_DepthOK(pt.behaviour.Behaviour):
    def __init__(self):
        self.bb = pt.blackboard.Blackboard()
        super(C_DepthOK, self).__init__(name="C_DepthOK")

    def update(self):
        if self.bb.get(DEPTH_BB) < SAM_MAX_DEPTH:
            return pt.Status.SUCCESS
        else:
            return pt.Status.FAILURE


class C_LeakOK(pt.behaviour.Behaviour):
    def __init__(self):
        self.bb = pt.blackboard.Blackboard()
        super(C_LeakOK, self).__init__(name="C_LeakOK")

    def update(self):
        # TODO confirm that leak==true means there is a leak
        if self.bb.get(LEAK_BB) == True:
            return pt.Status.FAILURE
        else:
            return pt.Status.SUCCESS



# currently unused because sam doesnt measure altitude yet
class C_AltOK(pt.behaviour.Behaviour):
    def __init__(self):
        self.bb = pt.blackboard.Blackboard()
        super(C_AltOK, self).__init__(name="C_AltOK")

    def update(self):
        # remove this when there is altitude available
        return pt.Status.SUCCESS

        if self.bb.get(ALTITUDE_BB) > SAM_MIN_ALTITUDE:
            return pt.Status.SUCCESS
        else:
            return pt.Status.FAILURE


class C_NewMissionPlanReceived(pt.behaviour.Behaviour):
    def __init__(self):
        """
        returns SUCCESS if there is a new and different
        mission plan received.
        Does not attempt to parse the mission plan and simply stores it in
        MISSION_PLAN_STR.

        return FAILURE otherwise.
        """

        self.bb = pt.blackboard.Blackboard()
        self.last_known_plan_msg=''
        super(C_NewMissionPlanReceived, self).__init__(name="C_NewMissionPlanReceived")


    def update(self):
        current_plan_msg = self.bb.get(MISSION_PLAN_MSG_BB)

        # a bad message or a duplicate
        if current_plan_msg is None or\
           current_plan_msg == self.last_known_plan_msg:
            return pt.Status.FAILURE

        # we ignore other types of plan operations for now.
        if current_plan_msg.op != IMC_PLANDB_OP_SET:
            return pt.Status.FAILURE

        # all is well, let the tree read it.
        self.last_known_plan_msg = current_plan_msg
        self.logger.info("New mission plan received:"+str(current_plan_msg))
        return pt.Status.SUCCESS



class C_PlanCompleted(pt.behaviour.Behaviour):
    def __init__(self):
        """
        If the currently know MissionPlan object in MISSION_PLAN_OBJ
        has no more actions left to do, return SUCCESS

        return FAILURE otherwise
        """
        self.bb = pt.blackboard.Blackboard()
        super(C_PlanCompleted, self).__init__(name="C_PlanCompleted?")

    def update(self):
        mission_plan = self.bb.get(MISSION_PLAN_OBJ_BB)
        if mission_plan is None or not mission_plan.completed:
            return pt.Status.FAILURE

        return pt.Status.SUCCESS


##########################################################################################
# NOT IMPLEMENTED YET
##########################################################################################

class C_HaveManualWaypoint(pt.behaviour.Behaviour):
    def __init__(self):
        #TODO implement to allow for manual single waypoints to be
        # processed by the tree, without sending a whole new plan

        self.bb = pt.blackboard.Blackboard()
        super(C_HaveManualWaypoint, self).__init__("C_HaveManualWaypoint")

    def update(self):
        return pt.Status.FAILURE


class C_ManualWaypointReceived(pt.behaviour.Behaviour):
    def __init__(self):
        #TODO implement to allow for manual single waypoints to be
        # processed by the tree, without sending a whole new plan

        self.bb = pt.blackboard.Blackboard()
        super(C_ManualWaypointReceived, self).__init__("C_ManualWaypointReceived")

    def update(self):
        return pt.Status.FAILURE