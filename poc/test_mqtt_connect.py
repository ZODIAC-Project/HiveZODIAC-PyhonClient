""" Simple MQTT Connect Test Script"""
import paho.mqtt.client as mqtt
def on_connect(c,u,f,rc): print('on_connect', rc); c.subscribe('control/reservations')
def on_message(c,u,msg): print('msg', msg.topic, msg.payload.decode())
c = mqtt.Client()
c.on_connect = on_connect
c.on_message = on_message
try:
    c.connect('localhost', 1883)
    c.loop_forever()
except Exception as e:
    print('connect error', e)