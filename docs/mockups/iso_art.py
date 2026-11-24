"""Isometric pictures for the landing mockup (2026-11-24).

Draws simple buildings from boxes in the RentFlow colours and puts the SVG between
<!--ART:name--> … <!--/ART--> in 2026-11-23-landing.html. Run again after a change:

    .venv\\Scripts\\python.exe docs\\mockups\\iso_art.py
"""
import math
import re
from pathlib import Path

C, S = math.cos(math.pi / 6), 0.5
K = 10  # px per unit

LINE = '#c3ccd4'
WALL = ('#ffffff', '#f3f5f7', '#e2e7ec')        # top, left (faces +y), right (faces +x)
PLATE = ('#eaedf0', '#e4e8ec', '#d6dce2')
GLASS = ('#d4e4ec', '#c7dbe5', '#b2c8d4')
ACC = ('#2bb497', '#148f77', '#0f7462')
ACC_SOFT = ('#b9e2d8', '#9dd3c6', '#82c1b2')
SLATE = ('#5b7186', '#4a6076', '#3b4f63')
GREY = ('#eef1f4', '#d9dfe5', '#c9d1d9')
HONEY = ('#f6c869', '#f2b544', '#d99d2f')       # the third colour (2026-11-24): an awning, a band, a door
LIT = ('#f9dc9a', '#f4cd78')                    # a lit window — someone rents it (left, right face)


class Scene:
    def __init__(self):
        self.items = []   # (svg string)
        self.pts = []

    def p(self, x, y, z):
        q = ((x - y) * C * K, (x + y) * S * K - z * K)
        self.pts.append(q)
        return q

    def poly(self, pts, fill, stroke=LINE, sw=0.6):
        s = ' '.join('%.1f,%.1f' % self.p(*q) for q in pts)
        st = ' stroke="%s" stroke-width="%s" stroke-linejoin="round"' % (stroke, sw) if stroke else ''
        self.items.append('<polygon points="%s" fill="%s"%s/>' % (s, fill, st))

    def box(self, x, y, z, w, d, h, col=WALL, stroke=LINE):
        top, left, right = col
        self.poly([(x, y + d, z), (x + w, y + d, z), (x + w, y + d, z + h), (x, y + d, z + h)], left, stroke)
        self.poly([(x + w, y, z), (x + w, y + d, z), (x + w, y + d, z + h), (x + w, y, z + h)], right, stroke)
        self.poly([(x, y, z + h), (x + w, y, z + h), (x + w, y + d, z + h), (x, y + d, z + h)], top, stroke)

    # a rectangle on the left face (y = const): x0..x1, z0..z1
    def on_l(self, y, x0, x1, z0, z1, fill, stroke=None):
        self.poly([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], fill, stroke, 0.5)

    # a rectangle on the right face (x = const): y0..y1, z0..z1
    def on_r(self, x, y0, y1, z0, z1, fill, stroke=None):
        self.poly([(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)], fill, stroke, 0.5)

    def row_l(self, y, x0, x1, n, w, z0, z1, fill=GLASS[1], lit=()):
        g = (x1 - x0 - n * w) / (n + 1)
        for i in range(n):
            a = x0 + g + i * (w + g)
            self.on_l(y, a, a + w, z0, z1, LIT[0] if i in lit else fill, '#d9b15c' if i in lit else '#a9bfcc')

    def row_r(self, x, y0, y1, n, w, z0, z1, fill=GLASS[2], lit=()):
        g = (y1 - y0 - n * w) / (n + 1)
        for i in range(n):
            a = y0 + g + i * (w + g)
            self.on_r(x, a, a + w, z0, z1, LIT[1] if i in lit else fill, '#d0a54e' if i in lit else '#9fb6c4')

    def band(self, x0, y0, x1, y1, z0, z1, col=ACC):
        """A coloured band around the two visible faces of a box (x0..x1, y0..y1)."""
        self.on_l(y1, x0, x1, z0, z1, col[1])
        self.on_r(x1, y0, y1, z0, z1, col[2])

    def tree(self, x, y, z, r=1.1, hgt=1.6):
        cx, cy = self.p(x, y, z)
        self.items.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="#d9dfe4"/>' % (cx, cy, r * K * 0.95, r * K * 0.5))
        tx, ty = self.p(x, y, z + hgt)
        self.items.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8a9aa8" stroke-width="2" stroke-linecap="round"/>' % (cx, cy, tx, ty))
        self.items.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#5fb8a3"/>' % (tx, ty - r * K * 0.55, r * K))
        self.items.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#7fc9b6"/>' % (tx - r * K * 0.3, ty - r * K * 0.85, r * K * 0.55))

    def svg(self, label):
        xs = [q[0] for q in self.pts]
        ys = [q[1] for q in self.pts]
        pad = 6
        vb = '%.0f %.0f %.0f %.0f' % (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
        return ('<svg viewBox="%s" role="img" aria-label="%s" xmlns="http://www.w3.org/2000/svg">' % (vb, label)
                + ''.join(self.items) + '</svg>')


def shops():
    s = Scene()
    s.box(0, 0, 0, 16, 12, 0.5, PLATE)
    z = 0.5
    s.box(2, 2, z, 12, 6, 6.6)
    # ground floor: three shops on the front (left) face, each with its own awning
    awn = [ACC, HONEY, ACC_SOFT]
    for i, x0 in enumerate((2, 6, 10)):
        s.on_l(8, x0 + 0.4, x0 + 2.7, z + 0.3, z + 2.4, GLASS[1], '#a9bfcc')
        s.on_l(8, x0 + 2.95, x0 + 3.6, z, z + 2.2, SLATE[1])
    s.on_l(8, 2, 14, z + 3.55, z + 3.7, WALL[2])            # floor line
    s.row_l(8, 2, 14, 6, 1.1, z + 4.2, z + 5.9, lit=(1, 4))
    s.band(2, 2, 14, 8, z + 6.25, z + 6.6)
    # right face: a big window below, three above
    s.on_r(14, 3, 7, z + 0.4, z + 2.6, GLASS[2], '#9fb6c4')
    s.on_r(14, 2, 8, z + 3.55, z + 3.7, '#d3dae1')
    s.row_r(14, 2, 8, 3, 1.1, z + 4.2, z + 5.9, lit=(2,))
    # pharmacy cross above the first shop
    cx, cz = 3.55, z + 3.05
    s.on_l(8, cx - 0.12, cx + 0.12, cz - 0.32, cz + 0.32, ACC[1])
    s.on_l(8, cx - 0.32, cx + 0.32, cz - 0.12, cz + 0.12, ACC[1])
    # roof units
    s.box(4, 3, z + 6.6, 2, 1.6, 0.8, GREY)
    s.box(10.5, 3.6, z + 6.6, 1.5, 1.4, 0.6, GREY)
    # awnings stick out of the front face (drawn after the face)
    for i, x0 in enumerate((2, 6, 10)):
        s.box(x0 + 0.25, 8, z + 2.5, 3.5, 0.9, 0.3, awn[i], None)
    s.tree(1.1, 10.6, z)
    s.tree(15.2, 11.0, z, 0.9, 1.3)
    return s.svg('Здание с аптекой, кафе и салоном')


def many():
    s = Scene()
    s.box(0, 0, 0, 18, 13, 0.5, PLATE)
    z = 0.5
    # tall office: a glass grid
    s.box(2, 2, z, 5, 5, 11)
    for f in range(7):
        z0 = z + 1.0 + f * 1.35
        s.row_l(7, 2, 7, 3, 1.1, z0, z0 + 0.95, lit={2: (1,), 5: (0,)}.get(f, ()))
        s.row_r(7, 2, 7, 3, 1.1, z0, z0 + 0.95, lit={3: (2,)}.get(f, ()))
    s.band(2, 2, 7, 7, z + 10.6, z + 11)
    s.on_l(7, 4.0, 5.0, z, z + 0.75, ACC[1])
    # mid building
    s.box(9, 1.5, z, 6, 4.5, 5.5)
    for z0 in (z + 0.8, z + 3.0):
        s.row_l(6, 9, 15, 4, 0.9, z0, z0 + 1.5)
        s.row_r(15, 1.5, 6, 3, 0.9, z0, z0 + 1.5)
    s.band(9, 1.5, 15, 6, z + 5.15, z + 5.5, HONEY)
    # warehouse with two gates
    s.box(9, 7.5, z, 7, 4, 3)
    for x0 in (10.0, 13.0):
        s.on_l(11.5, x0, x0 + 2.0, z, z + 2.0, GREY[2], '#b4bec8')
        for t in (0.5, 1.0, 1.5):
            s.on_l(11.5, x0, x0 + 2.0, z + t, z + t + 0.04, '#aab5bf')
    s.on_r(16, 8.3, 9.3, z, z + 1.7, HONEY[2])
    s.band(9, 7.5, 16, 11.5, z + 2.6, z + 3, ACC)
    s.tree(1.2, 11.4, z)
    s.tree(7.4, 11.8, z, 0.9, 1.3)
    return s.svg('Офис, здание и склад — несколько объектов')


def homes():
    s = Scene()
    s.box(0, 0, 0, 17, 12, 0.5, PLATE)
    z = 0.5
    # a house with a pitched roof (ridge along x)
    x0, x1, y0, y1, h = 2, 8, 4.5, 9.5, 3.2
    xa, xb, ya, yb, ym, rz = x0, x1, y0, y1 + 0.4, (y0 + y1) / 2, z + h + 2.4
    s.box(x0, y0, z, x1 - x0, y1 - y0, h)
    s.poly([(xa, ya, z + h), (xb, ya, z + h), (xb, ym, rz), (xa, ym, rz)], SLATE[2])     # back slope covers the flat top
    s.on_l(y1, 2.7, 4.2, z + 1.0, z + 2.5, GLASS[1], '#a9bfcc')
    s.on_l(y1, 6.0, 7.4, z + 1.0, z + 2.5, LIT[0], '#d9b15c')
    s.on_l(y1, 4.7, 5.6, z, z + 2.3, HONEY[1])
    s.on_r(x1, 6.2, 7.8, z + 1.0, z + 2.5, GLASS[2], '#9fb6c4')
    s.box(3.2, 5.2, z + h + 1.0, 0.8, 0.8, 2.2, GREY)                                        # chimney
    s.poly([(x1, y0, z + h), (x1, y1, z + h), (x1, ym, rz)], WALL[2])                         # gable
    s.on_r(x1, ym - 0.45, ym + 0.45, z + h + 0.5, z + h + 1.2, GLASS[2], '#9fb6c4')
    s.poly([(xa, ym, rz), (xb, ym, rz), (xb, yb, z + h), (xa, yb, z + h)], SLATE[1])         # front slope
    s.poly([(xb, ym, rz), (xb, yb, z + h), (xb, yb, z + h - 0.25), (xb, ym, rz - 0.25)], SLATE[2])
    # a block of flats with balconies
    s.box(10, 1, z, 5, 5, 8.6)
    floors = [z + 0.7 + f * 1.95 for f in range(4)]
    for f, z0 in enumerate(floors):
        s.row_l(6, 10, 15, 2, 1.2, z0, z0 + 1.3, lit={1: (0,), 3: (1,)}.get(f, ()))
        s.row_r(15, 1, 6, 2, 1.2, z0, z0 + 1.3, lit={2: (1,)}.get(f, ()))
    s.band(10, 1, 15, 6, z + 8.25, z + 8.6, HONEY)
    for z0 in floors[1:]:
        g = (5 - 2 * 1.2) / 3
        for i in range(2):
            a = 10 + g + i * (1.2 + g)
            s.box(a - 0.15, 6, z0 - 0.25, 1.5, 0.6, 0.55, ACC_SOFT, None)
    s.tree(9.0, 10.6, z)
    s.tree(15.6, 10.2, z, 0.9, 1.3)
    return s.svg('Дом и многоквартирный дом')


ART = {'shops': shops, 'many': many, 'homes': homes}

if __name__ == '__main__':
    page = Path(__file__).with_name('2026-11-23-landing.html')
    html = page.read_text(encoding='utf-8')
    for name, fn in ART.items():
        html = re.sub(r'<!--ART:%s-->.*?<!--/ART-->' % name, lambda m: '<!--ART:%s-->%s<!--/ART-->' % (name, fn()), html, flags=re.S)
    page.write_text(html, encoding='utf-8')
    print('ok')
