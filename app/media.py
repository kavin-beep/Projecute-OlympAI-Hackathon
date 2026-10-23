"""Image and audio provider adapter with a clearly labelled mock fallback.

No provider key is configured in this prototype, so both fall back to the mock
path: a generated placeholder image (SVG drawn here, deterministic from the
prompt) and browser text-to-speech (the frontend speaks the script).
"""
# Image and audio generation are future development (see README): today an image
# item is a placeholder drawn here, and an audio item is a script read aloud by the
# browser. Both are clearly labelled in the app as placeholders.

from __future__ import annotations

import base64
import colorsys
import hashlib
import os


def image_provider() -> str | None:
    """Name of the configured image provider, or None for the labelled mock."""
    return os.environ.get("IMAGE_API_KEY") or None


def audio_provider() -> str | None:
    """Name of the configured audio provider, or None for the labelled mock."""
    return os.environ.get("AUDIO_API_KEY") or None


def _palette(seed: str) -> list[str]:
    """Pick four related colours from the prompt so each placeholder image looks different."""
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    base = (h % 360) / 360
    out = []
    for i in range(4):
        r, g, b = colorsys.hsv_to_rgb((base + i * 0.08) % 1.0, 0.55, 0.45 + i * 0.12)
        out.append(f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}")
    return out


def generate_image(prompt: str, name: str) -> tuple[str, str]:
    """Return (data_url, generator). generator is 'live' or 'mock'."""
    if image_provider():
        # A real provider would be called here; none is configured in this build.
        pass
    # Draw seven soft circles on a gradient; positions and sizes come from a hash of the
    # prompt, so the same prompt always gives the same picture.
    colors = _palette(prompt or name)
    h = hashlib.sha256((prompt + name).encode()).digest()
    shapes = []
    for i in range(7):
        cx = 60 + h[i] % 520
        cy = 50 + h[i + 7] % 300
        r = 24 + h[i + 14] % 90
        shapes.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colors[i % len(colors)]}" opacity="0.55"/>'
        )
    label = (name or "Placeholder")[:40]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="{colors[0]}"/><stop offset="100%" stop-color="{colors[3]}"/>
</linearGradient></defs>
<rect width="640" height="400" fill="url(#g)"/>
<g>{''.join(shapes)}</g>
<rect x="0" y="330" width="640" height="70" fill="#0b0d12" opacity="0.72"/>
<text x="24" y="360" fill="#e8ecf6" font-family="system-ui,sans-serif" font-size="19">{_esc(label)}</text>
<text x="24" y="383" fill="#9aa4bd" font-family="system-ui,sans-serif" font-size="13">Placeholder image — no image provider configured</text>
</svg>"""
    # Return the SVG as a data URL the browser can show directly in an <img>.
    data = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{data}", "mock"


def generate_audio(script: str) -> tuple[str, str]:
    """Return (script, generator). The mock path is read aloud by the browser."""
    if audio_provider():
        pass
    return script, "mock"


def _esc(text: str) -> str:
    """Escape text for safe use inside SVG markup."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
