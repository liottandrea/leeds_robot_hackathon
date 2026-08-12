"""Pre-flight check: is the Ohbrain board answering on a serial port?

Runs the same probe the ohbot library uses (19200 baud, send "v\\n", expect a
reply containing v1 or v2) but without importing ohbot, which would trigger
motor init and audio playback as a side effect.
"""

import serial
import serial.tools.list_ports

BAUD = 19200
TIMEOUT = 0.5


def probe(device):
    """Send the version query and return the raw reply, or None on failure."""
    try:
        with serial.Serial(device, BAUD, timeout=TIMEOUT, write_timeout=TIMEOUT) as ser:
            ser.flushInput()
            ser.write(("v" + "\n").encode("latin-1"))
            return ser.readline()
    except Exception as e:
        print("    error: {}".format(e))
        return None


ports = list(serial.tools.list_ports.comports())

if not ports:
    print("No serial ports found at all. Is anything plugged in?")
    raise SystemExit(1)

print("Serial ports found:")
for p in ports:
    print("  {}  ({})".format(p.device, p.description))

found = []
print("\nProbing usb ports:")
for p in ports:
    # The ohbot library only probes ports whose name contains "usb" on macOS.
    if "usb" not in p.device:
        print("  {}  skipped (no 'usb' in name)".format(p.device))
        continue

    print("  {}  ...".format(p.device))
    reply = probe(p.device)
    if reply is None:
        continue

    print("    replied: {!r}".format(reply))
    if b"v1" in reply or b"v2" in reply:
        print("    -> OHBOT FOUND")
        found.append(p.device)

print()
if found:
    print("Ohbot is reachable on: {}".format(", ".join(found)))
else:
    print("No Ohbot found. Replug the USB-C cable and try again.")
    raise SystemExit(1)
