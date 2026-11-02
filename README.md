# Evrima Skin Studio

Created and directed by **Pops** — Discord: **_bruce.**  
Development, research and testing assistance: **OpenAI Codex (AI)**.

This private repository now contains the **application source from Skin Studio 1.4.1 — Idle Edition**.

## Browse the code

- [Skin Studio interface and features](app/outputs/EvrimaSkinEditor)
- [Shared 3D renderer and material code](app/outputs/EvrimaReplayViewer)
- [Additional material kernels](app/work)
- [Windows launcher](Open%20Skin%20Studio.cmd) and [Python entry point](launch.py)
- [Source file checksums](SOURCE-MANIFEST.json)
- [Development notes](DEVELOPMENT.txt)

The folder layout matches the published package. Application files are copied byte-for-byte from that release; newer replay-viewer-only work is not included.

## Download and run

**[Download Skin Studio 1.4.1](https://github.com/PopSmoke/evrima-skin-studio/releases/tag/v1.4.1)** and choose **Evrima-Skin-Studio-Idle-1.4.1.zip** under Assets.

Extract the entire ZIP, then run **Open Skin Studio.cmd**. Keep its console window open while Studio is running.

The complete download contains the source code, bundled Windows runtime, models, textures, adult idles and palette images. GitHub's Code tab contains the smaller source files and catalogs; a source checkout or GitHub-generated Source code ZIP alone is not a complete installation.

## Included in 1.4.1

- 29 dinosaur models and one adult idle per species.
- 98 pattern/texture choices, skin JSON import/export and raw numeric color editing.
- Color experiments, palettes, comparisons and live pattern audition.
- Corrected Austro, Hypsi and Ovi feather materials and transparency.
- Corrected Psitta painted textures and bristles.
- Visible launcher with startup/error reporting.

The full package is **845,316,998 bytes** compressed and **992,360,588 bytes** extracted. Lossless texture storage preserves source dimensions and decoded pixels.

ZIP SHA-256:

```text
088a3e40c4d243088c020618a760b0f202cf9de8367c96a3ed906f57a3f99e57
```

## Preview and credits

Lighting is approximate; bright/extreme colors do not establish native emission. Psitta's painted body does not support modern body-color editing. Some texture choices are asset previews rather than verified in-game patterns.

Game models, textures and other game content belong to their respective owners. Skin Studio is an independent tool, not an official product of The Isle. See [credits](CREDITS.txt) and [third-party notices](THIRD-PARTY-NOTICES.txt).
