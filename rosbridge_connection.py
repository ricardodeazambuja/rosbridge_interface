'''
Interface to Rosbridge using websockets

'''

from tornado.ioloop import IOLoop
from tornado import gen
from tornado.websocket import websocket_connect
# from tornado import escape
# from concurrent.futures import ThreadPoolExecutor # or ProcessPoolExecutor

import json

class rosbridge_interface(object):
    '''
    Python interface to Rosbridge

    rosrun rosbridge_server rosbridge_websocket &
    rosrun rosapi rosapi_node &

    callback: function that is going to process the msgs received from Rosbridge
    (do not use the normal brackets to pass callback the function)

    Information about Rosbridge protocol:
    https://github.com/RobotWebTools/rosbridge_suite/blob/groovy-devel/ROSBRIDGE_PROTOCOL.md

    To understand the msgs:
    http://wiki.ros.org/ROS/YAMLCommandLine
    '''
    def __init__(self, callback):
        # self._callback = self.good_call(callback)
        self._callback = callback
        self.conn = None

    # http://www.tornadoweb.org/en/stable/guide/coroutines.html#how-to-call-a-coroutine
    # def good_call(self,callback):
    #     @gen.coroutine
    #     def _foo(msg):
    #         callback(msg)
    #     return _foo


    def list_topics(self, url):
        '''
        Passes a list of all the available topics to the callback function and exits
        '''
        def convert_list_items_to_string(input_list):
            '''
            Converts list items to string.
            '''
            return [str(i) for i in input_list]

        @gen.coroutine
        def process_msgs():
            self.conn = yield websocket_connect(url)
            print "list_topics is connected!"
            cmd = { "op": "call_service", "service": "/rosapi/topics" }

            yield self.conn.write_message(json.dumps(cmd))

            topics = yield self.conn.read_message()

            self._callback(convert_list_items_to_string(json.loads(topics)['values']['topics']))

            self.conn.close()

        self.run_function = process_msgs

    def advertise(self):
        pass

    def publish(self, url, id, topic, period):
        '''
        Publishes to a topic what was returned after calling the callback (no arguments)
        function. If the callback returns None, the loop is aborted.

        period: 1/f => amount of time the system will wait until publish (call callback function first) again.

        Example - 1:
        publish("ws://localhost:9090","my_joint_commands","/robot/limb/left/joint_command", 0.1)

        msg:
        {'mode': 1, 'command': [0.0, 0.0, 0.0, 3.0, 2.55, -1.0, -2.07], \
        'names': ['left_w0', 'left_w1', 'left_w2', 'left_e0', 'left_e1', 'left_s0', 'left_s1']}

        callback:
        lambda _:{'mode': 1, 'command'... until the end of the msg

        Using rostopic command line:
        rostopic pub /robot/limb/left/joint_command baxter_core_msgs/JointCommand \
        "{mode: 1, command: [0.0, 0.0, 0.0, 3.0, 2.55, -1.0, -2.07], \
        names: ['left_w0', 'left_w1', 'left_w2', 'left_e0', 'left_e1', 'left_s0', 'left_s1']}" -r 100

        Or check online:
        https://groups.google.com/a/rethinkrobotics.com/forum/#!searchin/brr-users/command$20line/brr-users/MOoHAnM0YnY/KXAeKySB8vAJ
        http://sdk.rethinkrobotics.com/wiki/Arm_Control_Modes

        Example - 2:
        publish("ws://localhost:9090","set_command_timeout","/robot/limb/left/joint_command_timeout", 0.1)

        msg:
        1/0.5

        callback:
        lambda _:1/0.5
        '''
        @gen.coroutine
        def process_msgs():
            self.conn = yield websocket_connect(url)
            print id, "publisher is connected!"

            while True:
                self.msg = self._callback()
                if self.msg==None: break
                yield self.conn.write_message(json.dumps({'op':'publish', 'id':id, 'topic':topic, 'msg':self.msg}))
                yield gen.sleep(period)

            self.conn.close()

        self.run_function = process_msgs


    def subscribe(self, url, id, topic, msg_type, period=1, throttle_rate=0, queue_length=1, fragment_size=0, compression="none"):
        '''
        Subscribe to a topic and passes the received messages to the callback function.

        Example:
        subscribe("ws://localhost:9090","my_joint_states","/robot/joint_states","sensor_msgs/JointState", period=0.1)

        '''

        @gen.coroutine
        def process_msgs():
            self.conn = yield websocket_connect(url)
            print id, "subscriber is connected!"
            if fragment_size:
                cmd = {'op':'subscribe', 'id':id, 'topic':topic, 'type':msg_type, \
                        'throttle_rate':throttle_rate, 'queue_length':queue_length, \
                        'fragment_size':fragment_size, 'compression':compression}
            else:
                cmd = {'op':'subscribe', 'id':id, 'topic':topic, 'type':msg_type, \
                        'throttle_rate':throttle_rate, 'queue_length':queue_length, \
                        'compression':compression}

            yield self.conn.write_message(json.dumps(cmd))

            while True:
                received_msg = yield self.conn.read_message()
                if received_msg is None: break
                self.exit_code = self._callback(json.loads(received_msg))
                if self.exit_code: break
                yield gen.sleep(period)

            self.conn.close()

        self.run_function = process_msgs


    def read_and_actuate(self, url, id, period, topic_publ, topic_subs, msg_type, throttle_rate=0, queue_length=1, fragment_size=0, compression="none"):
        '''

        '''
        @gen.coroutine
        def process_msgs():
            self.sender = yield websocket_connect(url)
            self.reader = yield websocket_connect(url)

            cmd_reader = {'op':'subscribe', 'id':id+"subscriber", 'topic':topic_subs, 'type':msg_type, \
                          'throttle_rate':throttle_rate, 'queue_length':queue_length, \
                          'compression':compression}

            yield self.reader.write_message(json.dumps(cmd_reader)) #subscribes to the topic


            while True:
                # Reads the joint_states from the robot
                self.joint_states = yield self.reader.read_message()
                if self.joint_states is None: break

                # Sends the joint_states to the LSM and receives the next joint values
                self.next_joint_states = self._callback(json.loads(self.joint_states)) #interfaces to the LSM
                if self.next_joint_states is None: break

                # Sends the new_joint_states to the robot
                yield self.sender.write_message(json.dumps({'op':'publish', 'id':id+"publisher", 'topic':topic_publ, 'msg':self.next_joint_states}))

                # Sleeps if necessary...
                yield gen.sleep(period)

            self.sender.close()
            self.reader.close()

        self.run_function = process_msgs



    def run(self):
        '''
        This is a blocking function
        '''
        if self.conn != None:
            self.conn.close()
            # At least inside iPython after a ctrl+c the websocket would stay open.
            # Here I close it.

        io_loop = IOLoop.current()
        io_loop.clear_instance()
        IOLoop.instance().run_sync(self.run_function) #runs until run_function finishes


if __name__ == "__main__":

    #
    # Some examples
    #

    my_url = "ws://localhost:9090"

    # Creates the lists as memory buffers for the callback funtion
    labels = [None]
    effort = [None]
    position = [None]
    velocity = [None]

    def example_callback_subscriber(received_msg):
        labels[0]=received_msg['msg']['name']
        effort[0]=dict(zip(labels[0],received_msg['msg']['effort']))
        position[0]=dict(zip(labels[0],received_msg['msg']['position']))
        velocity[0]=dict(zip(labels[0],received_msg['msg']['velocity']))
        return 1 # forces it to stop after the first read

    def example_callback_publisher():
        return {'mode': 1, 'command': [0.0, 0.0, 0.0, 0.0, 2.55, -1.0, -1.07], \
                'names': ['left_w0', 'left_w1', 'left_w2', 'left_e0', 'left_e1', 'left_s0', 'left_s1']}

    def example_callback_topics(received_msg):
        print received_msg
        return 0

    def example_callback_read_and_actuate(received_msg):
        labels=received_msg['msg']['name']
        position=dict(zip(labels,received_msg['msg']['position']))

        return {'mode': 1, 'command': [position[li]+0.1 for li in ['left_w0', 'left_w1', 'left_w2', 'left_e0', 'left_e1', 'left_s0', 'left_s1']], \
                'names': ['left_w0', 'left_w1', 'left_w2', 'left_e0', 'left_e1', 'left_s0', 'left_s1']}

    subscriber = rosbridge_interface(example_callback_subscriber)
    publisher = rosbridge_interface(example_callback_publisher)
    topics = rosbridge_interface(example_callback_topics)

    closed_loop = rosbridge_interface(example_callback_read_and_actuate)

    publisher.publish(my_url,"my_joint_commands", "/robot/limb/left/joint_command", 1)

    subscriber.subscribe(my_url,"joint_states", "/robot/joint_states","sensor_msgs/JointState", period=0.1)

    topics.list_topics(my_url)

    closed_loop.read_and_actuate(my_url, "closed_loop", 0.1, \
                                 "/robot/limb/left/joint_command", "/robot/joint_states", \
                                 "sensor_msgs/JointState", throttle_rate=0, queue_length=1, fragment_size=0, compression="none")
