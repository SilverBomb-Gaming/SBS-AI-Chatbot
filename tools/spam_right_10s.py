import time
import vgamepad as vg

g = vg.VX360Gamepad()
print("Spamming DPAD_RIGHT for 10 seconds...")
end = time.time() + 10
while time.time() < end:
    g.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT); g.update()
    time.sleep(0.12)
    g.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT); g.update()
    time.sleep(0.12)
print("Done.")
time.sleep(1)
