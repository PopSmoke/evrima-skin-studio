"""Small, offline help and credits for Skin Studio."""
import tkinter as tk
from tkinter import ttk

AUTHOR = 'Pops'
DISCORD = '_bruce.'
CREDIT = 'Created by Pops'

# Keep examples descriptive: preview findings are not promises for every game
# pattern or server. No new assets or online dependency are needed for help.
PAGES = {
    'Getting started': [
        ('Make a design', 'Choose a dinosaur and pattern, then pick colors. You can keep editing while the preview updates. Drag the dinosaur to turn it and scroll over it to zoom.'),
        ('Try different patterns', 'Open Audition patterns to see your colors on several patterns at once. Leave it open while you edit. Choose a card and Apply when you find one you like.'),
        ('Keep your work', 'Save project keeps your colors and the full setup, including the dinosaur and pattern. Export skin creates a JSON skin file named after your design. Skin files do not select a dinosaur or pattern for you.'),
        ('Numbers or color picker?', 'Use the color squares for familiar colors. Use Raw RGBA (numbers) for exact or unusual values. X is red, Y is green and Z is blue. You can type negatives, decimals or values such as 1e6. Finished entries update automatically.'),
        ('Model and eyes', 'Growth changes the size preview. Prime shows supported prime shapes; visible prime changes begin above 75% growth in the current preview. Default eyes keeps the original eye appearance. Turn it off to try your own eye colors.'),
        ('What to expect in game', 'Studio is a guide to your design. Lighting, species and patterns can change how it looks in game. Check a finished skin in game before treating the preview as a match.'),
    ],
    'Color interactions': [
        ('What we have found', 'These interactions were observed in our decoded preview tests. The result depends on the dinosaur, pattern, sex, growth and other colors. They are useful starting points, not universal in-game rules.'),
        ('Sections can overlap', 'Body and Flank, Body and Underbelly, and Flank and Markings can affect the same areas. Changing one section may reveal, darken or recolor parts of another. The labels do not describe separate painted areas on every dinosaur.'),
        ('Negative colors can reveal patterns', 'A negative value can cancel part of a neighboring color where they overlap. That can create dark gaps or broken, speckled edges. Some speckles already belong to the original pattern. Start with a modest change and compare it with the original.'),
        ('Red, green and blue stay separate', 'Changing X does not change how Y or Z is read in the tested body-color calculation. But removing green can make the remaining red and blue look more purple. A color can look stronger because another color has been reduced.'),
        ('Brighter is not always better', 'Huge values can wash a color toward white. Try raising one or two channels while keeping the others lower. Negative values are not a general brightness boost, and the same change may darken one pattern while revealing another.'),
        ('Pink and purple', 'Keep green lower than red and blue for stronger pink or purple. If a color is barely visible, check negative values in overlapping sections as well as the color itself. Increasing every number may lose the hue you wanted.'),
        ('Male display and Markings', 'These two sections can interact too. Some of our strongest extreme-number differences changed with sex. Try both sexes rather than assuming Male display has no effect on a female preview.'),
        ('Glow, gold and silver', 'Bright-looking color is not the same as light emission. Color values alone have not demonstrated a general glow switch. Gold and silver tints do not turn the skin into reflective metal.'),
        ('A repeatable way to experiment', 'Save a project or checkpoint first. Change one section, compare the result, then try the neighboring section. Experiment Lab can make a series of variations. Record your in-game result in My skin library.'),
    ],
    'Tools explained': [
        ('Palettes', 'Browse ready-made color ideas and use one as a starting point.'),
        ('Experiment Lab', 'Make several variations without changing your working design. A value sweep tries a list of numbers. Locks keep selected colors unchanged. Discover looks for bright colors or unusual combinations. Apply a result to keep it; Undo takes you back.'),
        ('Compare skins', 'View two skins under matching conditions. Checkpoints keep earlier versions in this session. Save a checkpoint set if you want to use it after closing Studio.'),
        ('My skin library', 'Keep designs, favorites and notes together. Save the library to keep it after closing. In-game test notes are your own record of what you saw.'),
        ('See where colors act', 'Section influence tests one section and highlights where the picture changes. An unchanged picture does not always mean the section is unused; the effect may be hidden or already at its limit. Its percentage describes the whole picture, not the dinosaur’s body area.'),
        ('View settings', 'Change lighting to inspect your design. Preview detail controls how sharp the colored texture is while you work; higher settings can take longer. These controls do not change the exported skin colors.'),
        ('Design tools', 'Copy exact colors, save color combinations, check an export, or choose your usual workspace settings.'),
        ('Recovery copy', 'Choose a separate file to keep a rolling draft of your current design. Reopen that file after a restart. Turn recovery on again each session. Your library and Undo history are saved separately.'),
        ('The extra A value', 'A is preserved even when its field is hidden. On the tested body materials, changing it does not make the dinosaur transparent.'),
    ],
    'About': [
        ('Skin Studio', 'Created and directed by Pops.\nDiscord: _bruce.'),
        ('AI assistance', 'Development, research and testing assistance: OpenAI Codex (AI). Creative direction and project authorship: Pops.'),
        ('Game content', 'Dinosaur models, textures and other game content come from The Isle and belong to their respective owners. Pops’s authorship credit applies to Skin Studio, not to the original game assets.'),
        ('Independent project', 'Skin Studio is an independent tool and is not an official product of The Isle. All help is available offline.'),
    ],
}


class StudioHelp:
    def __init__(self, editor, page='Getting started'):
        self.editor = editor
        self.window = tk.Toplevel(editor.root)
        self.window.title('Skin Studio — Help & About')
        self.window.geometry('820x700'); self.window.minsize(700, 520)
        self.window.transient(editor.root)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(self.window, padding=16); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='A little help, when you need it', font=('Segoe UI', 18, 'bold')).pack(anchor='w', pady=(0, 12))
        self.tabs = ttk.Notebook(outer); self.tabs.pack(fill='both', expand=True)
        self.pages = {}; self.texts = {}
        for name in (*PAGES, 'Preview details'):
            frame = ttk.Frame(self.tabs, padding=10); self.tabs.add(frame, text=name)
            self.pages[name] = frame
            if name == 'Preview details':
                ttk.Label(frame, text='Optional technical notes for the current preview.').pack(anchor='w')
                ttk.Button(frame, text='Refresh notes', command=self.refresh_notes).pack(anchor='w', pady=(4, 8))
            text = tk.Text(frame, height=8, width=50, wrap='word', font=('Segoe UI', 11), relief='flat', padx=10, pady=8, background='#f7f9fb', foreground='#202c38')
            scroll = ttk.Scrollbar(frame, command=text.yview); scroll.pack(side='right', fill='y')
            text.configure(yscrollcommand=scroll.set); text.pack(fill='both', expand=True)
            text.tag_configure('heading', font=('Segoe UI', 12, 'bold'), spacing1=14, spacing3=5)
            self.texts[name] = text
            for heading, paragraph in PAGES.get(name, []):
                text.insert('end', heading+'\n', 'heading'); text.insert('end', paragraph+'\n\n')
            text.configure(state='disabled')
        self.close_button = ttk.Button(outer, text='Close', command=self.close)
        self.close_button.pack(anchor='e', pady=(12, 0))
        self.tabs.bind('<<NotebookTabChanged>>', lambda _: self.refresh_notes() if self.tabs.select() == str(self.pages['Preview details']) else None)
        self.show(page)

    def refresh_notes(self):
        text = self.texts['Preview details']; text.configure(state='normal')
        text.delete('1.0', 'end')
        text.insert('end', self.editor.details.get('1.0', 'end').strip() or 'The preview is still loading.')
        text.insert('end', '\n\n'+self.editor.shape_note.cget('text')+'\n'+self.editor.animation_count.get())
        text.configure(state='disabled')

    def show(self, page='Getting started'):
        self.tabs.select(self.pages[page]); self.window.lift()
        if page == 'Preview details': self.refresh_notes()

    def close(self):
        self.editor.help_window = None; self.window.destroy()
