"""Ohbot hello world.

Run from the project root so the ohbotData/ folder (motor calibration, speech
database, sounds) is shared by every script.

Importing ohbot calls init() automatically, so the robot must already be
plugged in before this line runs.
"""

from ohbot import ohbot

# Motor constants: 0 HEADNOD, 1 HEADTURN, 2 EYETURN, 3 LIDBLINK,
#                  5 BOTTOMLIP, 6 EYETILT   (4 is unused)

ohbot.reset()

# Look off to one side and lower the lids.
ohbot.move(ohbot.HEADTURN, 2)
ohbot.move(ohbot.LIDBLINK, 1)
ohbot.wait(2)

# Slowly centre the head, then speak.
ohbot.move(ohbot.HEADTURN, 5, 1)
ohbot.say("Hello World")

# Slowly increase the brightness of the eyes.
for x in range(0, 10):
    ohbot.setEyeColour(x, x, x)
    ohbot.wait(0.05)
    ohbot.setEyeColour(0, 0, 0)
    ohbot.wait(0.05)

# untilDone=False, so the program keeps running while Ohbot talks.
ohbot.say("I am now running in Python", False)

# Do the robot.
for x in range(0, 10):
    ohbot.move(ohbot.LIDBLINK, x)
    ohbot.setEyeColour(x, 10 - x, x)
    ohbot.wait(0.1)

ohbot.say("I can do the robot")

# Sweep each motor through its full range.
for m in range(0, 4):
    for pos in range(0, 10):
        ohbot.move(m, pos)
        ohbot.setEyeColour(pos, 10 - pos, 5)
        ohbot.wait(0.05)

ohbot.reset()
ohbot.say("That is enough ventriloquism for one day", True, False)
ohbot.setEyeColour(0, 0, 10)
ohbot.wait(1)

# Always close at the end: detaches the motors so they stop drawing current.
ohbot.close()
