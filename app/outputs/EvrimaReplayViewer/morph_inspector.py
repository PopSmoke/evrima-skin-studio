"""Manual preview of recovered shape targets, separate from recorded replay state."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import ImageTk
from morph_library import MorphLibrary
from mesh_renderer import GLRenderer
from replay_render import Camera


def preview_camera(base, full, yaw, pitch, width, height, zoom=1.):
    low = np.minimum(base.min(0), full.min(0))
    high = np.maximum(base.max(0), full.max(0))
    center = (low+high)/2
    camera = Camera(list(center), yaw, pitch, 1.)
    axes = np.asarray(camera.basis()[:2])
    extent = np.maximum(np.abs((base-center)@axes.T).max(0), np.abs((full-center)@axes.T).max(0))*2
    ratio = width/height
    camera.span = max(1., float(max(extent[1], extent[0]/ratio) if ratio >= 1 else max(extent[0], extent[1]*ratio))*1.2)*zoom
    return camera


class MorphInspector:
    def __init__(self, owner, visible=True):
        self.library = MorphLibrary()
        self.renderer = GLRenderer(1400, 950)
        self.window = tk.Toplevel(owner.root)
        if not visible:
            self.window.withdraw()
        self.window.title('Recovered model shapes — manual preview')
        self.window.geometry('1050x850')
        self.window.minsize(820, 700)
        self.closed = False
        self.pending = None
        self.photo = None
        self.image = None
        self.error = None
        self.yaw, self.pitch, self.zoom = -65., 12., 1.
        self.drag = None
        names = sorted(self.library.models)
        self.model = tk.StringVar(value='SK_Stegosaurus' if 'SK_Stegosaurus' in names else names[0])
        self.target = tk.StringVar()
        self.strength = tk.DoubleVar(value=1.)
        self.mode = tk.StringVar(value='Individual shape')
        self.food_remaining = tk.DoubleVar(value=25.)
        self.forced_opening = tk.DoubleVar(value=.5)
        bar = ttk.Frame(self.window, padding=12)
        bar.pack(fill='x')
        ttk.Label(bar, text='Model').pack(side='left')
        self.model_box = ttk.Combobox(bar, textvariable=self.model, values=names, state='readonly', width=28)
        self.model_box.pack(side='left', padx=8)
        self.model_box.bind('<<ComboboxSelected>>', lambda e: self.change_model())
        ttk.Button(bar, text='Reset view', command=self.reset_view).pack(side='right')
        modebar = ttk.Frame(self.window, padding=(12, 0, 12, 8))
        modebar.pack(fill='x')
        ttk.Label(modebar, text='Preview mode').pack(side='left')
        self.mode_box = ttk.Combobox(modebar, textvariable=self.mode, state='readonly', width=30)
        self.mode_box.pack(side='left', padx=8)
        self.mode_box.bind('<<ComboboxSelected>>', lambda e: self.change_mode())
        targetbar = ttk.Frame(self.window, padding=(12, 0, 12, 10))
        targetbar.pack(fill='x')
        ttk.Label(targetbar, text='Stored shape').pack(side='left')
        self.target_box = ttk.Combobox(targetbar, textvariable=self.target, state='readonly', width=52)
        self.target_box.pack(side='left', padx=8, fill='x', expand=True)
        self.target_box.bind('<<ComboboxSelected>>', lambda e: self.schedule())
        self.canvas = tk.Canvas(self.window, bg='#101921', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=12)
        self.canvas.bind('<Configure>', lambda e: self.schedule())
        self.canvas.bind('<ButtonPress-1>', lambda e: setattr(self, 'drag', (e.x, e.y, self.yaw, self.pitch)))
        self.canvas.bind('<B1-Motion>', self.rotate)
        self.canvas.bind('<ButtonRelease-1>', lambda e: setattr(self, 'drag', None))
        self.canvas.bind('<MouseWheel>', self.wheel)
        controls = ttk.Frame(self.window, padding=12)
        controls.pack(fill='x')
        self.readout = ttk.Label(controls)
        self.readout.pack(anchor='w')
        self.manual_controls = ttk.Frame(controls)
        self.manual_controls.pack(fill='x')
        ttk.Scale(self.manual_controls, from_=0, to=1, variable=self.strength, command=lambda v: self.schedule()).pack(fill='x', pady=8)
        buttons = ttk.Frame(self.manual_controls)
        buttons.pack(fill='x')
        for label, value in [('Base shape', 0.), ('Half strength', .5), ('Full stored shape', 1.)]:
            ttk.Button(buttons, text=label, command=lambda v=value: self.set_strength(v)).pack(side='left', padx=(0, 8))
        self.carcass_controls = ttk.Frame(controls)
        for label, variable, maximum in [('Food remaining (%)', self.food_remaining, 100), ('Forced body opening', self.forced_opening, 1)]:
            row = ttk.Frame(self.carcass_controls)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label, width=24).pack(side='left')
            ttk.Scale(row, from_=0, to=maximum, variable=variable, command=lambda v: self.schedule()).pack(side='left', fill='x', expand=True)
        presets = ttk.Frame(self.carcass_controls)
        presets.pack(fill='x', pady=(4, 0))
        for label, food, opening in [('Intact', 100., 0.), ('Half eaten', 50., 0.), ('25% + opening', 25., .5), ('Depleted', 0., 0.)]:
            ttk.Button(presets, text=label, command=lambda f=food, o=opening: self.set_carcass(f, o)).pack(side='left', padx=(0, 8))
        self.note = ttk.Label(controls, wraplength=980, justify='left')
        self.note.pack(anchor='w', pady=(10, 0))
        ttk.Label(controls, text='Manual preview, not recorded replay state. Neutral shading; no skin materials, death pose, automatic growth or health damage. Drag to rotate; scroll to zoom. One model is loaded at a time.', wraplength=980, justify='left').pack(anchor='w', pady=(8, 0))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.change_model()

    def change_model(self):
        names = self.library.models[self.model.get()]['names']
        self.target_box.configure(values=names)
        self.target.set(names[0])
        self.strength.set(1.)
        modes = ['Individual shape']
        if 'BodyGore' in names:
            modes.append('Carcass food preview')
        self.mode_box.configure(values=modes)
        if self.mode.get() not in modes:
            self.mode.set('Individual shape')
        self.change_mode()
        self.reset_view()

    def change_mode(self):
        carcass = self.mode.get() == 'Carcass food preview'
        self.manual_controls.pack_forget()
        self.carcass_controls.pack_forget()
        (self.carcass_controls if carcass else self.manual_controls).pack(fill='x', before=self.note)
        self.target_box.configure(state='disabled' if carcass else 'readonly')
        self.schedule()

    def set_carcass(self, food, opening):
        self.food_remaining.set(food)
        self.forced_opening.set(opening)
        self.schedule()

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -65., 12., 1.
        self.schedule()

    def set_strength(self, value):
        self.strength.set(value)
        self.schedule()

    def rotate(self, event):
        if self.drag:
            x, y, yaw, pitch = self.drag
            self.yaw = yaw + (event.x-x)*.35
            self.pitch = max(-80, min(80, pitch+(event.y-y)*.25))
            self.schedule()

    def wheel(self, event):
        self.zoom = max(.2, min(4., self.zoom * (.9 if event.delta > 0 else 1.1)))
        self.schedule()

    def schedule(self):
        if not self.closed and self.pending is None:
            self.pending = self.window.after(25, self.redraw)

    def redraw(self):
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        if self.closed:
            return
        try:
            mesh = self.library.load(self.model.get())
            if self.mode.get() == 'Carcass food preview':
                food, opening = float(self.food_remaining.get()), float(self.forced_opening.get())
                points, applied = self.library.carcass_shape(food, opening)
                # All corners of the capped two-input blend keep the camera stable.
                full = np.concatenate([self.library.carcass_shape(f, o)[0] for f, o in ((100, 0), (100, 1), (80, 1), (0, 1), (0, 0))])
                self.readout.configure(text=f'Food remaining: {food:.1f}% · Forced opening: {opening:.2f}')
                weights = ', '.join(f'{name}: {value:.3f}' for name, value in applied.items())
                self.note.configure(text=weights+'\nShared game formula on available targets; species overrides unverified. Fresh-state simulation, not health damage. No interior meshes or decay materials are added.')
            else:
                strength = float(self.strength.get())
                points = self.library.shape(self.target.get(), strength)
                full = self.library.shape(self.target.get(), 1.)
                indices, _, _ = self.library.targets[self.target.get()]
                self.readout.configure(text=f'Shape strength: {strength:.0%} · {len(indices):,} affected vertices')
                self.note.configure(text=f'{self.model.get()} · {self.target.get()}\nSource shape offsets applied at original model scale. Lighting normals are recalculated from the preview geometry.')
            width = max(320, min(1400, self.canvas.winfo_width()))
            height = max(240, min(950, self.canvas.winfo_height()))
            camera = preview_camera(mesh.positions, full, self.yaw, self.pitch, width, height, self.zoom)
            self.image = self.renderer.draw(mesh, [points], camera, width, height)
            self.photo = ImageTk.PhotoImage(self.image)
            self.canvas.delete('all')
            self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
            self.error = None
        except Exception as error:
            self.error = str(error)
            self.canvas.delete('all')
            self.image = self.photo = None
            self.readout.configure(text='Shape preview unavailable')
            self.note.configure(text=str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.library.clear()
        self.renderer.close()
        self.window.destroy()


if __name__ == '__main__':
    from types import SimpleNamespace
    root = tk.Tk()
    root.withdraw()
    inspector = MorphInspector(SimpleNamespace(root=root))
    def close():
        inspector.close()
        root.destroy()
    inspector.window.protocol('WM_DELETE_WINDOW', close)
    root.mainloop()
