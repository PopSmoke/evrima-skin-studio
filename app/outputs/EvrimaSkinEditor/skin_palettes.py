"""Rendered palette library, independent of the editor's graphics worker."""
import copy
import json
import hashlib
from pathlib import Path
from skin_document import validate

ROOT = Path(__file__).resolve().parent / 'palettes'


def load_library():
    path = ROOT / 'library.json'
    if not path.exists():
        raise ValueError('The tested palette library has not been built yet.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('format') != 'evrima-tested-palettes-1':
        raise ValueError('Unsupported palette library')
    project = ROOT.parents[2]
    stale = []
    for name, digest in data.get('provenance', {}).items():
        source = (project / name).resolve()
        if not source.is_relative_to(project.resolve()) or not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            stale.append(name)
    data['_stale_sources'] = stale
    return data


def apply_palette(document, palette):
    """Apply six body colors; preserve species, pattern, growth and eye choices."""
    doc = copy.deepcopy(document)
    for slot in ('md', 'm', 'b', 'f', 'u', 'd'):
        doc['colors'][slot] = list(palette['colors'][slot])
    doc['name'] = palette['name']
    # Imported extra overrides can shadow the six palette colors.
    doc['extra_overrides'] = {}
    doc.pop('source_glitch', None)
    doc['import_notes'] = [
        'Palette: ' + palette['name'] + '. Tested in the decoded material preview; in-game emission is unverified.',
        'Reference tests: adult male, pattern 1, variation 8, standard, original eyes. Other settings require their own preview.'
    ]
    return validate(doc)


def evidence_matches(doc, test):
    settings = test['settings']
    return all(doc.get(key) == settings[key] for key in ('species', 'pattern', 'growth', 'female', 'variation', 'prime', 'default_eyes'))


def filter_palettes(data, species, query='', level='All ranges', vivid_only=False, order='Library order'):
    results = []
    for palette in data['palettes']:
        test = next((t for t in palette['tests'] if t['settings']['species'] == species), None)
        if test is None:
            continue
        m = test['metrics']
        if level != 'All ranges' and palette['range'] != level:
            continue
        if query.strip().lower() not in (palette['name'] + ' ' + m['observed_family']).lower():
            continue
        if vivid_only and not (m.get('vivid_percent', 0) >= 10 and m['white_percent'] <= 15):
            continue
        results.append((palette, test))
    if order == 'Most vivid first':
        results.sort(key=lambda pair: (-pair[1]['metrics'].get('vivid_percent', 0), pair[1]['metrics']['white_percent'], pair[0]['name']))
    elif order == 'Least white first':
        results.sort(key=lambda pair: (pair[1]['metrics']['white_percent'], -pair[1]['metrics'].get('vivid_percent', 0), pair[0]['name']))
    return [p for p, t in results]


def open_browser(editor):
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageTk
    data = load_library()
    window = tk.Toplevel(editor.root)
    window.title('Tested palette library — rendered results')
    window.geometry('1120x810')
    window.minsize(930, 730)
    header = ttk.Frame(window, padding=12)
    header.pack(fill='x')
    ttk.Label(header, text=f'{len(data["palettes"])} palettes • glow-like color experiments', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    ttk.Label(header, text='These are decoded-preview tests, not verified in-game emission. No bloom or glow was added to the pictures.', wraplength=1040).pack(anchor='w', pady=5)
    if data['_stale_sources']:
        ttk.Label(header, text='Reference tests are from an earlier renderer/catalog revision. Apply and inspect again; saved pictures have not been retested.', wraplength=1040, foreground='#9a4c00').pack(anchor='w')
    filters = ttk.Frame(header)
    filters.pack(fill='x')
    search = tk.StringVar()
    ttk.Label(filters, text='Search').pack(side='left')
    ttk.Entry(filters, textvariable=search, width=25).pack(side='left', padx=6)
    level = tk.StringVar(value='All ranges')
    box = ttk.Combobox(filters, textvariable=level, state='readonly', values=['All ranges'] + list(dict.fromkeys(p['range'] for p in data['palettes'])), width=20)
    box.pack(side='left', padx=6)
    species = tk.StringVar(value=editor.doc['species'] if editor.doc['species'] in data['tested_species'] else data['tested_species'][0])
    ttk.Label(filters, text='Test model').pack(side='left', padx=(12, 2))
    species_box = ttk.Combobox(filters, textvariable=species, state='readonly', values=data['tested_species'], width=18)
    species_box.pack(side='left', padx=6)
    options = ttk.Frame(header)
    options.pack(fill='x', pady=(8, 0))
    vivid_only = tk.BooleanVar(value=False)
    ttk.Checkbutton(options, text='Vivid colors with less white', variable=vivid_only, command=lambda: refresh()).pack(side='left')
    order = tk.StringVar(value='Library order')
    order_box = ttk.Combobox(options, textvariable=order, state='readonly', values=['Library order', 'Most vivid first', 'Least white first'], width=22)
    order_box.pack(side='left', padx=12)
    ttk.Label(options, text='Ranking applies to the selected test model.').pack(side='left')
    area = ttk.Frame(window, padding=(12, 0))
    area.pack(fill='both', expand=True)
    left = ttk.Frame(area)
    left.pack(side='left', fill='y', padx=(0, 14))
    listing = tk.Listbox(left, width=35, exportselection=False, font=('Segoe UI', 10))
    listing.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(left, command=listing.yview)
    scroll.pack(side='right', fill='y')
    listing.configure(yscrollcommand=scroll.set)
    right = ttk.Frame(area)
    right.pack(side='left', fill='both', expand=True)
    title = ttk.Label(right, font=('Segoe UI', 13, 'bold'))
    title.pack(anchor='w')
    picture = ttk.Label(right)
    picture.pack(anchor='center', pady=8)
    details = tk.Text(right, height=15, wrap='word', font=('Segoe UI', 10), relief='flat', padx=8, pady=8)
    details.pack(fill='both', expand=True)
    footer = ttk.Frame(window, padding=12)
    footer.pack(fill='x')
    ttk.Label(footer, text='Applies body colors to your current dinosaur. Keeps eyes and model settings. Undo is available.', wraplength=700).pack(side='left')
    visible = []
    selected = [None]

    def show(*_):
        indices = listing.curselection()
        if not indices:
            return
        palette = visible[indices[0]]
        selected[0] = palette
        test = next(t for t in palette['tests'] if t['settings']['species'] == species.get())
        title.configure(text=palette['name'])
        image_path = (ROOT / test['image']).resolve()
        if not image_path.is_relative_to(ROOT.resolve()):
            raise ValueError('Palette image leaves library')
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != test['file_sha256']:
            raise ValueError('Palette reference image has changed since testing')
        with Image.open(image_path) as source:
            im = source.copy()
        im.thumbnail((660, 340))
        picture.photo = ImageTk.PhotoImage(im)
        picture.configure(image=picture.photo)
        m = test['metrics']
        lines = [f'Tested on {species.get()}: pattern 1 • adult male • variation 8 • standard • original eyes.',
                 f'Observed bright-area color: {m["highlight_hex"]} ({m["observed_family"]}).',
                 f'Bright model pixels: {m["bright_percent"]:.1f}% • near-white pixels: {m["white_percent"]:.1f}%.',
                 f'Vivid model pixels: {m.get("vivid_percent", 0):.1f}% (bright, saturated display colors).',
                 f'Body texture samples outside display range: {test["shader_metrics"]["outside_display_percent"]:.1f}%.',
                 'These measurements describe this picture, not light emission or nighttime visibility.',
                 'Current model/settings match this test.' if evidence_matches(editor.doc, test) else 'Your current model/settings differ. Apply and inspect the live preview before judging the result.',
                 palette['description']]
        if test.get('same_render_as'):
            lines.append('Identical rendered pixels to: ' + test['same_render_as'] + '. Larger raw values did not change this tested image.')
        if test.get('material_support') == 'experimental':
            lines.append('This dinosaur’s material adapter is experimental.')
        lines.extend(['', 'Exact raw RGBA (not hex swatches):'] + [f'{k}: ' + ', '.join(repr(v) for v in values) for k, values in palette['colors'].items()])
        details.configure(state='normal')
        details.delete('1.0', 'end')
        details.insert('1.0', '\n'.join(lines))
        details.configure(state='disabled')

    def refresh(*_):
        query = search.get().strip().lower()
        visible[:] = filter_palettes(data, species.get(), query, level.get(), vivid_only.get(), order.get())
        listing.delete(0, 'end')
        selected[0] = None
        for palette in visible:
            listing.insert('end', palette['name'])
        if visible:
            listing.selection_set(0)
            show()
        else:
            title.configure(text='No matching palettes')
            picture.configure(image='')
            details.configure(state='normal'); details.delete('1.0', 'end'); details.configure(state='disabled')

    def apply():
        indices = listing.curselection()
        if indices:
            palette = visible[indices[0]]
            editor.mode.set('Raw RGBA (numbers)')
            editor.commit(apply_palette(editor.doc, palette), show_design=True)
            editor.refresh_colors()
            window.destroy()

    ttk.Button(footer, text='Apply palette', command=apply).pack(side='right')
    listing.bind('<<ListboxSelect>>', show)
    species.trace_add('write', refresh)
    search.trace_add('write', refresh)
    level.trace_add('write', refresh)
    order.trace_add('write', refresh)
    refresh()
    return window
