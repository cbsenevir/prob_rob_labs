#!/usr/bin/env python

###########################################
# Unfinished tasks for A3:
#   1. modify the launch file to set parameter for landmark(x, y, r, h, color)
#   2. validate the calculated P_ip and then publish


import rospy
from sympy import symbols, Matrix, sin, cos, atan2, simplify, lambdify
from geometry_msgs.msg import PoseStamped, TwistStamped, Twist
from tf2_msgs.msg import TFMessage
from sensor_msgs.msg import CameraInfo
from std_msgs.msg import Float64MultiArray
from tf.transformations import euler_from_quaternion
import tf2_ros


def init_functions():
    x, y, theta, t_cx, t_cy, t_cz, x_l, y_l, r_l, h_l, f_x, f_y, c_x, c_y \
        = symbols("x y theta t_cx t_cy t_cz x_l y_l r_l h_l f_x f_y c_x c_y")
        
    x_c = cos(theta)*t_cx - sin(theta)*t_cy + x
    y_c = sin(theta)*t_cx + cos(theta)*t_cy + y
    phi = atan2(y_l - y_c, x_l - x_c)

    x1 = x_l - r_l*sin(phi)
    y1 = y_l + r_l*cos(phi)
    x2 = x_l + r_l*sin(phi)
    y2 = y_l - r_l*cos(phi)

    P_1g = Matrix([[x1, y1, 0, 1]]).T
    P_2g = Matrix([[x2, y2, 0, 1]]).T
    P_3g = Matrix([[x2, y2, h_l, 1]]).T
    P_4g = Matrix([[x1, y1, h_l, 1]]).T
    P_ig = [P_1g, P_2g, P_3g, P_4g]

    T_mr = Matrix([[cos(theta), -sin(theta), 0, x],
                [sin(theta),  cos(theta), 0, y],
                [0,           0,          1, 0],
                [0,           0,          0, 1]    
                ])

    T_ro = Matrix([[ 0,  0, 1, t_cx],
                [-1,  0, 0, t_cy],
                [ 0, -1, 0, t_cz],
                [ 0,  0, 0, 1]    
                ])

    T_mo = T_mr * T_ro
    # print(T_mo.inv())
    T_om = simplify(T_mo.inv())
    # print(T_om)

    P_io = []
    for element in P_ig:
        P_io.append(T_om * element)

    Proj_mat = Matrix([[f_x, 0,   c_x],
                    [0,   f_y, c_y],
                    [0,   0,   1]
                    ])

    auxiliary_vec = []
    for element in P_io:
        auxiliary_vec.append(Proj_mat * element[:3, :])

    P_ip_list = []
    for element in auxiliary_vec:
        P_ip_list.append(element[:2, :]/element[2,0])

    P_ip = Matrix([[P_ip_list[0][0,0]],
                [P_ip_list[0][1,0]],
                [P_ip_list[1][0,0]],
                [P_ip_list[1][1,0]],
                [P_ip_list[2][0,0]],
                [P_ip_list[2][1,0]],
                [P_ip_list[3][0,0]],
                [P_ip_list[3][1,0]],
    ])

    states = Matrix([x, y, theta])
    Hx = P_ip.jacobian(states)
    Hx_func = lambdify((x, y, theta, t_cx, t_cy, t_cz, x_l, y_l, r_l, h_l, f_x, f_y, c_x, c_y), Hx)

    P_ip_func = lambdify((x, y, theta, t_cx, t_cy, t_cz, x_l, y_l, r_l, h_l, f_x, f_y, c_x, c_y), P_ip)
    
    return Hx_func, P_ip_func

class measurement_pred:
    def __init__(self):     
        # Initiate the parameters
        self.x = 0; self.y = 0; self.theta = 0 # State vector
        self.f_x = 0; self.f_y = 0; self.c_x = 0; self.c_y = 0 # Camera projection matrix
        self.t_cx = 0; self.t_cy = 0; self.t_cz = 0; # Robot frame to camera frame translation
        self.x_l = rospy.get_param('/measurement_predictor/landmark_x', 'default')
        self.y_l = rospy.get_param('/measurement_predictor/landmark_y', 'default')
        self.r_l = rospy.get_param('/measurement_predictor/landmark_r', 'default')
        self.h_l = rospy.get_param('/measurement_predictor/landmark_h', 'default')
        self.color = rospy.get_param('/measurement_predictor/landmark_color', 'default')
        self.CameraInfo_Retrieved = 0
        
        # Declare the subscribers and publishers
        self.gt_pose = rospy.Subscriber('/jackal/ground_truth/pose', PoseStamped, self.update_mmt_pred, queue_size = 1)
        self.CameraInfo_sub = rospy.Subscriber('/front/left/camera_info', CameraInfo, self.update_CameraInfo, )
        self.mmt_pred_pub = rospy.Publisher('/'+self.color+'/pred_feature', Float64MultiArray, queue_size = 1)
        
        # Create tf listener and initiate transform parameters
        self.tfBuffer = tf2_ros.Buffer()
        self.listener = tf2_ros.TransformListener(self.tfBuffer)
        trans = self.tfBuffer.lookup_transform('base_link', 'front_camera', rospy.Time.now(), rospy.Duration(1.0))
        self.t_cx = trans.transform.translation.x
        self.t_cy = trans.transform.translation.y
        self.t_cz = trans.transform.translation.z
        
        # Initiate functions
        self.Hx, self.P_ip = init_functions()
        #rospy.loginfo(f"initialized")
    def update_CameraInfo(self, data):
        #rospy.loginfo(f"update camerainfo called")
        self.f_x = data.K[0]
        self.c_y = data.K[2]
        self.f_y = data.K[4]
        self.c_y = data.K[5]
        
        self.image_width = data.width
        self.image_height = data.height
        self.CameraInfo_Retrieved = 1
    
    def update_mmt_pred(self, data):
        rospy.loginfo(f"updated measurement called")
        self.x = data.pose.position.x
        self.y = data.pose.position.y
        self.theta = euler_from_quaternion([data.pose.orientation.x, data.pose.orientation.y, 
                                            data.pose.orientation.z, data.pose.orientation.w])
                
        #rospy.loginfo(f"start check")       
        if self.CameraInfo_Retrieved == 1:
            P_ip = self.P_ip(self.x, self.y, self.theta,
                             self.f_x, self.f_y, self.c_x, self.c_y,
                             self.x_l, self.y_l, self.r_l, self.h_l,
                             self.t_cx, self.t_cy, self.t_cz)

            
            valid_features = []
            for i in range(0, 8, 2):
                x_pixel = P_ip[i]
                y_pixel = P_ip[i+1]
                if 0 <= x_pixel <= image_width and 0 <= y_pixel <= image_height: 
                    valid_features.append((x_pixel, y_pixel))
            
            if valid_features:
                msg = Float64MultiArray()
                msg.data = [point for feature in valid_features for point in feature]
                self.mmt_pred_pub.publish(msg)

def main():
    rospy.init_node('measurement_predictor')
    rospy.loginfo('starting measurement_predictor')
    measurement_pred()
    rospy.spin()
    rospy.loginfo('done')

if __name__=='__main__':
    main()
