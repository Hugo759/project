#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# LONET EDGE COMPUTING PYTHON SCRIPT
# -----------------------------------------------------------------------------
# Description: To connect the RPi to a Firebase DB, acquire a GPS Signal from
# an MQTT Broker, calculate the BLE Beacon Distance, allocate BLE locations
# by correlating GPS and to publish results to Firebase DB every 5 minutes.

# IOT Standards & Protocols
# Waterford Institute of Technology
# November/December 2018
# -----------------------------------------------------------------------------
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

from bluepy.btle import Scanner, DefaultDelegate
import time
import math

import paho.mqtt.client as mqtt
import urllib.parse
import json

import threading

# -----------------------------------------------------------------------------
# SET UP FIREBASE CREDENTIALS, ENSURE PRODUCT KEY IS IN SAME FOLDER
# -----------------------------------------------------------------------------
cred = credentials.Certificate('productkey.json')
default_app = firebase_admin.initialize_app(cred, {
   'databaseURL': 'https://iot-project-3a8f7.firebaseio.com/'
})
root = db.reference()

# -----------------------------------------------------------------------------
# DETECT BLE BEACONS, CALCULATE DISTANCE >> The Key is the MAC!!
# -----------------------------------------------------------------------------
# a DICT for all of our Beacon MAC's and the Beacon Names.
beaconMACs = {"f1:2b:88:07:2c:42": "WIT Beacon 1",
              "fe:0c:dd:90:7c:aa": "WIT Beacon 2",
              "E7:00:A2:F5:43:42": "CMU Beacon 1",
              "C0:03:36:1A:17:7E": "CMU Beacon 2"}


class ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)


scanner = Scanner().withDelegate(ScanDelegate())


def listen_for_beacons():
    while 1:
        devices = scanner.scan(.5)
        for dev in devices:
            for MAC in beaconMACs.keys():
                if dev.addr == MAC:

                    # Get the GPS of this reading...
                    print(" ")
                    print("BLE: %s, MAC: %s, RSSI= %d dB" % (beaconMACs[MAC], dev.addr, dev.rssi))
                    ts = time.gmtime()
                    date_stamp = str(ts[2]) + "/" + str(ts[1]) + "/" + str(ts[0])

                    # Distance Calculation
                    n = 15  # Path loss exponent(n) = 1.5
                    c = -45  # Environment constant(C) = 10
                    a0 = -20  # Average RSSI value at d0
                    x = float((dev.rssi - a0) / (-10 * n))
                    distance = (math.pow(10, x) * 100) + c
                    print("DISTANCE: " + str(distance))

                    # Get's the MQTT recent Coordinates and sets Lat and Lon Global Variables
                    set_gps_coordinates()

                    # Adds this detection to the MAC dict. (Key is MAC)
                    add_detection(MAC, dev.rssi, date_stamp, distance)


# -----------------------------------------------------------------------------
# GPS COORDINATE ACQUISITION via MQTT
# -----------------------------------------------------------------------------
# Define event callbacks
def on_connect(client, userdata, flags, rc):
    print("GPS Coordinates MQTT Connection Result: " + str(rc))


def on_subscribe(client, obj, mid, granted_qos):
    print("GPS Subscribed,  QOS granted: " + str(granted_qos))


def on_message(client, obj, msg):
    print(" ")
#    print("MQTT Topic: " + msg.topic + ", Payload: " + str(msg.payload.decode("utf-8")))
    coord = json.loads(msg.payload.decode("utf-8"))
    global lat
    lat = coord['lat']
    global lon
    lon = coord['lon']
    # print("Lat Variable Set: %s" % lat)
    # print("Lon Variable Set: %s" % lon)


mqttc = mqtt.Client()

# Assign event callbacks
mqttc.on_message = on_message
mqttc.on_connect = on_connect
mqttc.on_subscribe = on_subscribe

# parse mqtt url for connection details
# Below URL is for testing, use the in folder script test_gps
# url_str = "mqtt://iot.eclipse.org:1883/jbizzboz/home/gps"
# MQTT URL published by a seperate Android App and Device
url_str = "tcp://broker.hivemq.com:1883/lonetisthehighnet"
url = urllib.parse.urlparse(url_str)
base_topic = url.path[1:]

# Connect
if url.username:
    mqttc.username_pw_set(url.username, url.password)
mqttc.connect(url.hostname, url.port)

# Start subscribe, with QoS level 0
mqttc.subscribe(base_topic + "/#", 0)

# Start the MQTT Loop
mqttc.loop_start()

# short sleep for the connection to establish and allow lat/lon to be filled once
time.sleep(4)


# When called by a Beacon being Identified, accesses the GPS Payload in Msg
def set_gps_coordinates():
    mqttc.on_message = on_message


# -----------------------------------------------------------------------------
# BUFFER THREAD & CORRELATE RELATIVE POSITION WITH GPS
# -----------------------------------------------------------------------------
# Creates a thread for a timer with callback.
def timer_for_closest_detections():
    # Timer thread set to 10 seconds...
    timer = threading.Timer(35.0, get_closest_detections)
    timer.start()


# Create Dicts for all Beacons and their readings
all_beacon_detections = {}
for key in beaconMACs:
    all_beacon_detections[key] = {}


# Add detections to Dict
def add_detection(MAC, rssi, date_stamp, distance):
    print("----------------------------")
   # print("Adding Detection to BLE Dict")
    # The below is adding the measurements to RSSI
    all_beacon_detections[MAC][rssi] = (lat, lon, date_stamp, distance)
   # print("-- All Beacon Detections -- ")
    print(all_beacon_detections)


# Get the lowest RSSI value from Dict
def get_closest_detections():
    for MAC in all_beacon_detections:
        # set variable to each beacon in dict
        current_beacon = all_beacon_detections[MAC]
        # bool ensures that we execute a Max et al only if there are values in the dict.
        if bool(current_beacon):
            # get the record for the beacon with the closest detection (max of negative number)
            closest = max(current_beacon)
            print(" ")
            print(" ")
            print(" <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <->")
            print("> CLOSEST BEACON DETECTION:")
            print("> MAC:      " + MAC)
            print("> RSSI:     " + str(closest))
            print("> Distance: " + str(current_beacon[closest][3]))
            print(" <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <-> <->")
            print(" ")
            print(" ")
            closest_location = current_beacon[closest]

            # Clear current data from the dict
            all_beacon_detections[MAC].clear()

            # Send the data
            new_location = root.child('location').push({
                'MAC': MAC,
                'lat': closest_location[0],
                'long': closest_location[1],
                'distance': closest_location[3],
                'active': True,
                'timestamp': closest_location[2]
            })
            db.reference('users/{0}'.format(new_location.key)).get()
    # Start the timer again for this method callback
    timer_for_closest_detections()


# Activate timer on startup
timer_for_closest_detections()


def main():
    listen_for_beacons()


if __name__ == '__main__':
    main()




# -----------------------------------------------------------------------------
# THE BELOW CODE IS A WORK IN PROGRESS
# WE TRIED TWO SEPERATE TRILATERATION ALGORITHMS BUT COULD NOT FIGURE
# OUT HOW TO IMPLEMENT THE CALCULATIONS GIVEN OUR SPECIFIC USE CASE
# > THEY ARE KEPT HERE FOR FUTURE REFERENCE AND POSSIBLE ENHANCEMENTS
# -----------------------------------------------------------------------------

# import scipy
# from scipy import optimize
# import numpy

# # Create list of location values
# locations = []
# # Create list of distances
# distances = []

#   # NEW METHOD WITH OPTIMISATION INSTEAD OF MINIMISATION OF A SINGLE RSSI
#     locations.append((lat, lon))
#     distances.append(distance)
#     print(locations)
#     print(distances)
#     if len(distances) == 3:
#         tri_coordinates(locations, distances)
#         locations.clear()
#         distances.clear()

# Sends the 'lowest' RSSI to be the initial guess to help the optimize algo
#            best_guess = (closest_location[0], closest_location[1])
#            print("here")
#            print(best_guess)
#            # Activates the optimisation
#            try:
#                print("XXXXXXXXXXXXXXXX this should be optimised?")
#                location_optimal = optimize_method(best_guess)
#                print(str(location_optimal))
#            except Exception as e:
#                print(e)
#                print("No DICE Amigo")
#                raise
#
#            # Clear the testing lists
#            global distances
#            distances.clear()
#            global locations
#            locations.clear()
#
#
# def tri_coordinates(locations, distances):
#     earth_radius = 6371
#     DistA = distances[0] / 1000
#     DistB = distances[1] / 1000
#     DistC = distances[2] / 1000
#     LatA = locations[0][0]
#     LonA = locations[0][1]
#     LatB = locations[1][0]
#     LonB = locations[1][1]
#     LatC = locations[2][0]
#     LonC = locations[2][1]
#
#     # using authalic sphere
#     # if using an ellipsoid this step is slightly different
#     # Convert geodetic Lat/Long to ECEF xyz
#     #   1. Convert Lat/Long to radians
#     #   2. Convert Lat/Long(radians) to ECEF
#
#     xA = earth_radius * (math.cos(math.radians(LatA)) * math.cos(math.radians(LonA)))
#     yA = earth_radius * (math.cos(math.radians(LatA)) * math.sin(math.radians(LonA)))
#     zA = earth_radius * (math.sin(math.radians(LatA)))
#
#     xB = earth_radius * (math.cos(math.radians(LatB)) * math.cos(math.radians(LonB)))
#     yB = earth_radius * (math.cos(math.radians(LatB)) * math.sin(math.radians(LonB)))
#     zB = earth_radius * (math.sin(math.radians(LatB)))
#
#     xC = earth_radius * (math.cos(math.radians(LatC)) * math.cos(math.radians(LonC)))
#     yC = earth_radius * (math.cos(math.radians(LatC)) * math.sin(math.radians(LonC)))
#     zC = earth_radius * (math.sin(math.radians(LatC)))
#
#     P1 = numpy.array([xA, yA, zA])
#     P2 = numpy.array([xB, yB, zB])
#     P3 = numpy.array([xC, yC, zC])
#
#     # from wikipedia
#     # transform to get circle 1 at origin
#     # transform to get circle 2 on x axis
#
#     ex = (P2 - P1) / (numpy.linalg.norm(P2 - P1))
#     i = numpy.dot(ex, P3 - P1)
#     ey = (P3 - P1 - i * ex) / (numpy.linalg.norm(P3 - P1 - i * ex))
#     ez = numpy.cross(ex, ey)
#     d = numpy.linalg.norm(P2 - P1)
#     j = numpy.dot(ey, P3 - P1)
#
#     x = (math.pow(DistA, 2) - math.pow(DistB, 2) + math.pow(d, 2)) / (2 * d)
#     y = ((math.pow(DistA, 2) - math.pow(DistC, 2) + math.pow(i, 2) + math.pow(j, 2)) / (2 * j)) - ((i / j) * x)
#
#     # only one case shown here
#     try:
#         z = math.sqrt(math.pow(DistA, 2) - math.pow(x, 2) - math.pow(y, 2))
#     except:
#         z = float('nan')
#
#     # triPt is an array with ECEF x,y,z of trilateration point
#     triPt = P1 + x * ex + y * ey + z * ez
#
#     # convert back to lat/long from ECEF
#     # convert to degrees
#     lat = math.degrees(math.asin(triPt[2] / earth_radius))
#     lon = math.degrees(math.atan2(triPt[1], triPt[0]))
#
#     print("><><><><><><><><><><><><")
#     print(" ")
#     print("><><><><><><>><><><><><><>><><>><><><>")
#     print(" the results are :::")
#     print(str(lat))
#     print(str(lon))
#     print("they up there ???????????????????????????")

# # -----------------------------------------------------------------------------
# # Mean Square Error
# # locations: [ (lat1, long1), ... ]
# # distances: [ distance1, ... ]
# def mse(x, locations_list, distances_list):
#    mse = 0.0
#    for location, distance in zip(locations_list, distances_list):
#        distance_calculated = great_circle_distance(x[0], x[1], location[0], location[1])
#        mse += math.pow(distance_calculated - distance, 2.0)
#    return mse / len(data)
#
#
# # -----------------------------------------------------------------------------
# OPTIMISATION ALGORITHM
# # initial_location: (lat, long)
# # locations: [ (lat1, long1), ... ]
# # distances: [ distance1,     ... ]
# def optimize_method(best_guess):
#    #mse_result = mse(x, locations, distances)
#    result = scipy.optimize.minimize(
#        1,  # mse_result,  # mse, # The error function
#        best_guess,  # initial_location,  # The initial guess
#        args=(locations, distances),  # Additional parameters for mse
#        method='L-BFGS-B',  # The optimisation algorithm
#        options={
#            'ftol': 0.00001,  # Tolerance
#            'maxiter': 10000000 # 1e+7  # Maximum iterations
#        })
#    location = result.x
#    return location
