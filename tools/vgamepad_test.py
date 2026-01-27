import time
import vgamepad as vg

g = vg.VX360Gamepad()
print("Pressing A 5 times...")
for _ in range(5):
    g.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    g.update()
    time.sleep(0.1)
    g.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
    g.update()
    time.sleep(0.4)
print("Done.")
