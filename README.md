arduino-cli compile --upload \
  --fqbn esp32:esp32:featheresp32 \
  -p /dev/ttyACM0 .


"""
source ~/esp32env/bin/activate
mpremote connect /dev/ttyACM1 fs cp server.py :main.py
"""