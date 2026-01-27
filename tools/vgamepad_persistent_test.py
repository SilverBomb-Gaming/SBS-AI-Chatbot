import time
import vgamepad as vg

g = vg.VX360Gamepad()
print("Virtual controller created. Pressing A every second for 30s...")
for i in range(30):
    g.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    g.update()
    time.sleep(0.2)
    g.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    g.update()
    time.sleep(0.8)
print("Done. Controller will now be released.")
time.sleep(2)
