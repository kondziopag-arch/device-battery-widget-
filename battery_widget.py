import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime

APP_TITLE = "Device Battery"
POLL_SECONDS = 20
LOW_BATTERY = 20

# Logi Bolt receiver: VID 046D, PID C548.
# The app discovers the HID++ feature index at runtime (Unified Battery 0x1004).
VID = 0x046D
BOLT_PID = 0xC548
UNIFIED_BATTERY = 0x1004


def read_hidpp_reply(dev, request, timeout_ms=650):
    """Send a 20-byte HID++ long report and wait briefly for its response."""
    packet = bytes(request + [0] * (20 - len(request)))
    try:
        dev.write(packet)
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            remaining = max(1, int((deadline - time.time()) * 1000))
            data = dev.read(20, timeout_ms=remaining)
            if data and len(data) >= 5:
                # Ignore unrelated notifications/reports.
                if data[0] == 0x11:
                    return list(data)
    except Exception:
        return None
    return None


def query_logitech_slot(dev, slot):
    # ROOT.getFeature(UNIFIED_BATTERY)
    reply = read_hidpp_reply(
        dev, [0x11, slot, 0x00, 0x0B,
              (UNIFIED_BATTERY >> 8) & 0xFF, UNIFIED_BATTERY & 0xFF]
    )
    if not reply or len(reply) < 6:
        return None
    feature_index = reply[4]
    if feature_index in (0x00, 0xFF):
        return None

    # UNIFIED_BATTERY.get_status (function 1, sub-id 0xB)
    reply = read_hidpp_reply(dev, [0x11, slot, feature_index, 0x1B])
    if not reply or len(reply) < 5:
        return None
    level = reply[4]
    if level > 100:
        return None
    return level


def scan_logitech():
    """Return readings for receiver slots 1..6, or an explanatory status."""
    try:
        import hid
    except ImportError:
        return {}, "Missing package: install requirements with install.bat"

    try:
        candidates = hid.enumerate(VID, BOLT_PID)
    except Exception as exc:
        return {}, f"Could not enumerate Bolt receiver: {exc}"

    # Windows exposes the receiver's long HID++ collection as usage 0x0002
    # on usage page 0xFF00. Prefer that collection.
    candidates = [
        item for item in candidates
        if item.get("usage_page") == 0xFF00 and item.get("usage") == 0x0002
    ]
    if not candidates:
        return {}, "Bolt receiver not found. Check that it is plugged in."

    readings = {}
    errors = []
    for item in candidates:
        dev = None
        try:
            dev = hid.device()
            dev.open_path(item["path"])
            dev.set_nonblocking(False)
            for slot in range(1, 7):
                value = query_logitech_slot(dev, slot)
                if value is not None:
                    readings[slot] = value
            if readings:
                break
        except Exception as exc:
            errors.append(str(exc))
        finally:
            if dev:
                try:
                    dev.close()
                except Exception:
                    pass

    if not readings:
        detail = errors[0] if errors else "No paired device answered the battery request."
        return {}, detail
    return readings, "Connected to Logi Bolt"


class BatteryWidget:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("330x300")
        self.root.minsize(300, 270)
        self.root.configure(bg="#111827")
        self.root.attributes("-topmost", True)

        self.readings = {}
        self.busy = False
        self.last_update = tk.StringVar(value="Starting…")
        self.status = tk.StringVar(value="Looking for Logi Bolt receiver…")
        self.pin_var = tk.BooleanVar(value=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#F9FAFB",
                        font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground="#9CA3AF", font=("Segoe UI", 8))
        style.configure("Name.TLabel", foreground="#F9FAFB",
                        font=("Segoe UI Semibold", 10))
        style.configure("Value.TLabel", foreground="#F9FAFB",
                        font=("Segoe UI Semibold", 19))
        style.configure("TCheckbutton", background="#111827", foreground="#D1D5DB")
        style.configure("TButton", font=("Segoe UI", 9), padding=5)

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="DEVICE BATTERY", font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Checkbutton(header, text="Pin", variable=self.pin_var,
                        command=self.toggle_pin).pack(side="right")

        self.device_rows = {}
        self.add_device(outer, "keyboard", "⌨", "Logitech MX Keys for Business",
                        "Keyboard · Logi Bolt")
        self.add_device(outer, "mouse", "🖱", "Logitech MX Master 3S",
                        "Mouse · Logi Bolt")
        self.add_device(outer, "jabra", "🎧", "Jabra Evolve2 85",
                        "Headset · Jabra Link")

        ttk.Separator(outer).pack(fill="x", pady=10)
        ttk.Label(outer, textvariable=self.status, style="Muted.TLabel",
                  wraplength=290).pack(anchor="w")
        ttk.Label(outer, textvariable=self.last_update, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Refresh now", command=self.refresh).pack(side="left")
        ttk.Button(buttons, text="Quit", command=self.root.destroy).pack(side="right")

        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def add_device(self, parent, key, glyph, name, connection):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=6)
        left = ttk.Frame(frame)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text=f"{glyph}  {name}", style="Name.TLabel").pack(anchor="w")
        ttk.Label(left, text=connection, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        value = ttk.Label(frame, text="—", style="Value.TLabel")
        value.pack(side="right", padx=(6, 0))
        self.device_rows[key] = value

    def toggle_pin(self):
        self.root.attributes("-topmost", self.pin_var.get())

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.status.set("Checking devices…")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        readings, message = scan_logitech()
        self.root.after(0, lambda: self.update_ui(readings, message))

    def update_ui(self, readings, message):
        self.busy = False
        self.readings = readings

        # Bolt slot numbers are discovered automatically. Logitech receiver
        # pairing order is commonly keyboard in slot 1 and mouse in slot 2.
        # If your devices were paired in another order, their labels may swap.
        for key, slot in (("keyboard", 1), ("mouse", 2)):
            label = self.device_rows[key]
            if slot in readings:
                pct = readings[slot]
                label.configure(text=f"{pct}%", foreground=self.level_color(pct))
            else:
                label.configure(text="—", foreground="#9CA3AF")

        self.device_rows["jabra"].configure(
            text="SDK needed", foreground="#9CA3AF"
        )
        self.status.set(message + " · Jabra Link battery integration not enabled")
        self.last_update.set("Updated " + datetime.now().strftime("%H:%M:%S"))
        self.root.after(POLL_SECONDS * 1000, self.refresh)

    @staticmethod
    def level_color(pct):
        if pct <= LOW_BATTERY:
            return "#F87171"
        if pct <= 40:
            return "#FBBF24"
        return "#34D399"


if __name__ == "__main__":
    root = tk.Tk()
    app = BatteryWidget(root)
    root.mainloop()
