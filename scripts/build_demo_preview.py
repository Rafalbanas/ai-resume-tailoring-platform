#!/usr/bin/env python3
"""Build a labelled screenshot slideshow, not a video or a latency measurement.

Uses Pillow from the project dependencies. No application, AI or account access.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

MEDIA = Path(__file__).resolve().parents[1] / 'docs' / 'media'
SLIDES = [
    ('01-job-form.png', '1/4 | Synthetic job description'),
    ('match-report-overview.png', '2/4 | Local Gemma match report'),
    ('03-export-status.png', '3/4 | Export timeout (not a successful export)'),
    ('04-history.png', '4/4 | Saved application history'),
]


def main():
    frames = []
    for filename, caption in SLIDES:
        with Image.open(MEDIA / filename) as source:
            image = ImageOps.contain(source.convert('RGB'), (720, 500))
        frame = Image.new('RGB', (720, 564), '#101827')
        frame.paste(image, ((720 - image.width) // 2, 48 + (500 - image.height) // 2))
        draw = ImageDraw.Draw(frame)
        draw.text((12, 8), 'SYNTHETIC DEMO | Screenshot slideshow - not real-time footage', fill='white')
        draw.text((12, 26), caption, fill='white')
        frames.append(frame)
    target = MEDIA / 'cvtailor-report-preview.gif'
    frames[0].save(target, save_all=True, append_images=frames[1:], duration=2500, loop=0, optimize=True)
    print(f'{target.name}: {len(frames)} slides, {target.stat().st_size} bytes')


if __name__ == '__main__':
    main()
