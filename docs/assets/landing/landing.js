/* The Electrify Earth globe.
 *
 * Three stacked canvases: `under` holds what never moves (the sphere's shading and the
 * pencil ring), `earth` is redrawn as the globe turns, `over` holds the brush stroke.
 *
 * Everything on `earth` is drawn from the geography, hatching included, and every line
 * point keeps its own pressure, so each mark turns with the land under it. A texture
 * fixed to the screen would make the land look as if it slid beneath a second sheet.
 *
 * d3-geo does the two things that are hard to do by hand, clipping polygons at the horizon
 * and point-in-country tests. Lines and dots are projected here directly, which is what
 * lets a 33,000-point coastline carry per-segment widths at a useful frame rate.
 *
 * Dark mode is the same Earth seen from space at the end of a very late sunset. The Sun has
 * just gone behind the globe's lower left limb, so the whole face is night: the air along
 * the limb still glows from sunset orange through blue to the green of the airglow, and
 * behind it are the stars that really lie around the Sun's direction today (Yale Bright Star
 * Catalogue, stars.json), with the Milky Way and the zodiacal light. A fourth canvas, `sky`,
 * holds them behind the whole page. The camera is fixed in space and the Earth turns under
 * it, so the sky and the sunset stay still while the land goes round.
 */
(function () {
  'use strict';

  var BASE = window.EARTH_BASE || 'assets/landing/';
  var INK = '38,35,31';
  var RED = '163,44,16';
  var RAD = Math.PI / 180;
  var TAU = Math.PI * 2;
  var SERIF = '"Zen Old Mincho", Georgia, serif';
  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var START = [-48, -16, 0];   // opens on the side of the Earth with every atlas in view
  var SPIN_DEG_S = 3.2;
  var AUTO_FPS = 24;           // the hand-drawn cadence, and half the work
  var NEW_ATLAS = 'contribute/new-atlas/';
  var NARROW_W = 1040;         // below this the page stacks: the same width as in landing.css
  var HATCH_DEG = 1.15;        // between pencil lines
  var HATCH_STEP = 1.6;        // between the points of one line
  var HATCH_POLE = [-30, -35]; // the South Atlantic; its far end is the North Pacific
  var TONE_ALPHA = 0.95;       // the white over a cell the model has looked at
  var RED_MW = 100;            // a 0.1 degree cell at or above this is red: 382 cells, 35% of capacity

  /* The night. MOON is the pencil by night, STAR the ink, EMBER the vermilion. */
  var MOON = '160,182,226', STAR = '240,230,208', EMBER = '255,140,88';
  var EARTH_DEG = 22;          // the globe's angular radius from the camera, which sets the sky's scale
  var SUN_PSI = 215 * Math.PI / 180;   // where the Sun has set: lower left, counter-clockwise from the right
  var SUN_AT = 0.9;            // and how far out, in globe radii: just inside the limb, so it is hidden

  /* Everything the two themes draw differently. A line set is [rgb, alpha]. The light values
     are the ink sketch's, unchanged. */
  var THEMES = {
    light: {
      dark: false,
      wash: [INK, 0.05], hatch: [INK, 0.26], grat: [INK, 0.13], border: [INK, 0.3],
      region: [INK, 0.28], ghost: [INK, 0.2], coast: [INK, 0.62],
      inkWash: [INK, 0.05], inkGhost: [INK, 0.35], ink: [INK, 0.95], red: RED,
      tone: [255, 253, 248], toneAlpha: TONE_ALPHA,
      ramp: [[0, 252, 240, 233], [0.25, 249, 222, 209], [0.5, 241, 176, 152],
             [0.726, 224, 112, 80], [0.85, 198, 68, 38], [1, 163, 44, 16]],
      mark: [RED, 0.92], halo: null,
      ring: [INK, 0.4, 0.2], tick: [INK, 0.55], label: [INK, 0.62],
      brush: null, spatter: [INK, 0.82]
    },
    /* By night the land EarthPV has looked at is lit a cool slate, and its solar glows from
       ember to gold: brighter is more. The brush is the sunset itself, gold to rose. */
    dark: {
      dark: true,
      wash: [MOON, 0.07], hatch: [MOON, 0.15], grat: [MOON, 0.08], border: [MOON, 0.26],
      region: [MOON, 0.2], ghost: [MOON, 0.14], coast: [MOON, 0.52],
      inkWash: [MOON, 0.05], inkGhost: [STAR, 0.3], ink: [STAR, 0.9], red: EMBER,
      tone: [150, 172, 226], toneAlpha: 0.42,
      ramp: [[0, 96, 48, 82], [0.25, 160, 52, 66], [0.5, 218, 76, 44],
             [0.726, 255, 136, 56], [0.85, 255, 190, 100], [1, 255, 240, 200]],
      mark: ['255,232,184', 0.95], halo: ['255,150,80', 0.2],
      ring: ['186,200,232', 0.3, 0.15], tick: ['200,210,236', 0.5], label: ['205,214,238', 0.66],
      brush: [[255, 228, 172], [255, 170, 104], [240, 112, 124]], spatter: ['240,112,124', 0.82]
    }
  };

  function el(id) { return document.getElementById(id); }

  function rgba(c) { return 'rgba(' + c[0] + ',' + c[1] + ')'; }

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

  function normed(v) {
    var l = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / l, v[1] / l, v[2] / l];
  }

  function cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }

  /* The colour ramp of the solar raster, as little-endian RGBA words. */
  function buildRamp(stops) {
    var out = new Uint32Array(256), s = 0;
    for (var i = 0; i < 256; i++) {
      var u = i / 255;
      while (s < stops.length - 2 && u > stops[s + 1][0]) s++;
      var a = stops[s], b = stops[s + 1], t = (u - a[0]) / (b[0] - a[0]);
      var mix = function (k) { return a[k] + (b[k] - a[k]) * t; };
      out[i] = (255 << 24) | (mix(3) << 16) | (mix(2) << 8) | mix(1);
    }
    return out;
  }

  function mulberry(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* Smooth 1-D noise in [0, 1]: a brush's pressure along a stroke. */
  function pressure(n, rand, period) {
    var out = new Float32Array(n), a = rand(), b = rand(), k = 0;
    for (var i = 0; i < n; i++) {
      if (k >= period) { k = 0; a = b; b = rand(); }
      var t = k / period;
      out[i] = a + (b - a) * t * t * (3 - 2 * t);
      k++;
    }
    return out;
  }

  /* ---------------------------------------------------------------- paper and grain */

  function paperTile() {
    var size = 512, c = document.createElement('canvas');
    c.width = c.height = size;
    var x = c.getContext('2d'), rand = mulberry(77);
    var img = x.createImageData(size, size), d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var v = rand() * 8;
      d[i] = 92; d[i + 1] = 78; d[i + 2] = 54; d[i + 3] = v;
    }
    x.putImageData(img, 0, 0);
    x.lineCap = 'round';
    for (var f = 0; f < 420; f++) {   // kozo fibres; drawn with their wrapped copies so the tile repeats
      var px = rand() * size, py = rand() * size, a = rand() * TAU, len = 12 + rand() * 46;
      var bend = (rand() - 0.5) * 22, light = rand() < 0.55;
      x.strokeStyle = light ? 'rgba(255,255,250,' + (0.12 + rand() * 0.3) + ')'
                            : 'rgba(96,80,56,' + (0.03 + rand() * 0.08) + ')';
      x.lineWidth = 0.4 + rand() * 0.8;
      for (var ox = -size; ox <= size; ox += size) {
        for (var oy = -size; oy <= size; oy += size) {
          x.beginPath();
          x.moveTo(px + ox, py + oy);
          x.quadraticCurveTo(px + ox + Math.cos(a) * len / 2 - Math.sin(a) * bend,
                             py + oy + Math.sin(a) * len / 2 + Math.cos(a) * bend,
                             px + ox + Math.cos(a) * len, py + oy + Math.sin(a) * len);
          x.stroke();
        }
      }
    }
    return c;
  }

  /* ------------------------------------------------------------------- the night sky */

  /* The Sun's direction today, as an equatorial unit vector (J2000 axes), from the low
     precision formula of the Astronomical Almanac: good to a hundredth of a degree. Also its
     ecliptic longitude and the obliquity, for the zodiacal light. */
  function sunToday(date) {
    var n = date.getTime() / 86400000 + 2440587.5 - 2451545.0;
    var g = (357.528 + 0.9856003 * n) * RAD;
    var lam = (280.460 + 0.9856474 * n + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * RAD;
    var eps = (23.439 - 0.0000004 * n) * RAD;
    return { dir: [Math.cos(lam), Math.cos(eps) * Math.sin(lam), Math.sin(eps) * Math.sin(lam)],
             lam: lam, eps: eps };
  }

  /* The camera: looking along A, the Sun at SUN_AT globe radii from the centre towards SUN_PSI,
     celestial north as near to up as that allows. Seen from inside the sky, east is on the
     left, which X = A x U gives. Solved by a few rounds of fixed-point iteration. */
  function skyFrame(sun) {
    var beta = Math.atan(SUN_AT * Math.tan(EARTH_DEG * RAD));
    var A = sun.slice(), U, X;
    for (var it = 0; it < 12; it++) {
      U = normed([-A[2] * A[0], -A[2] * A[1], 1 - A[2] * A[2]]);
      X = normed(cross(A, U));
      var c = Math.cos(SUN_PSI), s = Math.sin(SUN_PSI);
      var toSun = [c * X[0] + s * U[0], c * X[1] + s * U[1], c * X[2] + s * U[2]];
      A = normed([sun[0] - Math.sin(beta) * toSun[0], sun[1] - Math.sin(beta) * toSun[1],
                  sun[2] - Math.sin(beta) * toSun[2]]);
    }
    U = normed([-A[2] * A[0], -A[2] * A[1], 1 - A[2] * A[2]]);
    X = normed(cross(A, U));
    return { A: A, U: U, X: X };
  }

  /* Equatorial (J2000) to galactic: x to the Galactic Centre, z to the north galactic pole. */
  var GAL = [[-0.0548755604, -0.8734370902, -0.4838350155],
             [0.4941094279, -0.4448296300, 0.7469822445],
             [-0.8676661490, -0.1980763734, 0.4559837762]];

  function hash3(x, y, z) {
    var h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 1274126177);
    h = Math.imul(h ^ (h >>> 13), 1103515245);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  function noise3(x, y, z) {
    var xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
    var u = x - xi, v = y - yi, w = z - zi;
    u = u * u * (3 - 2 * u); v = v * v * (3 - 2 * v); w = w * w * (3 - 2 * w);
    var a = hash3(xi, yi, zi), b = hash3(xi + 1, yi, zi);
    var c = hash3(xi, yi + 1, zi), d = hash3(xi + 1, yi + 1, zi);
    var e = hash3(xi, yi, zi + 1), f = hash3(xi + 1, yi, zi + 1);
    var g = hash3(xi, yi + 1, zi + 1), h = hash3(xi + 1, yi + 1, zi + 1);
    var x1 = a + (b - a) * u, x2 = c + (d - c) * u, x3 = e + (f - e) * u, x4 = g + (h - g) * u;
    var y1 = x1 + (x2 - x1) * v, y2 = x3 + (x4 - x3) * v;
    return y1 + (y2 - y1) * w;
  }

  function fbm(x, y, z, octaves) {
    var sum = 0, amp = 0.5, norm = 0;
    for (var o = 0; o < octaves; o++) {
      sum += amp * noise3(x, y, z);
      norm += amp;
      x = x * 2.03 + 17.1; y = y * 2.03 + 3.7; z = z * 2.03 + 9.3;
      amp *= 0.5;
    }
    return sum / norm;
  }

  function smoothstep(a, b, x) {
    var t = clamp01((x - a) / (b - a));
    return t * t * (3 - 2 * t);
  }

  /* The Milky Way's light in one direction (galactic unit vector), roughly as it looks to
     the eye: a thin disc brightest towards Sagittarius, the bulge, the Cygnus and Carina
     clouds, and the dark Great Rift with dust lanes along the plane. Returns [disc, bulge]. */
  function milkyWay(gx, gy, gz) {
    var b = Math.asin(gz) / RAD, ab = Math.abs(b);
    if (ab > 45) return null;
    var l = Math.atan2(gy, gx) / RAD;
    var width = 4.5 + 4 * Math.exp(-l * l / 1800);
    var along = 0.3 + 0.7 * Math.exp(-l * l / 3200) + 0.3 * Math.exp(-(l - 78) * (l - 78) / 260) +
                0.2 * Math.exp(-(l + 72) * (l + 72) / 380);
    var disc = Math.exp(-b * b / (2 * width * width)) * along + 0.18 * Math.exp(-ab / 16) * along;
    var bulge = Math.exp(-(l * l / 128 + (b + 1.5) * (b + 1.5) / 90));
    var clumps = fbm(gx * 7, gy * 7, gz * 7, 3);
    var dust = fbm(gx * 15 + 5, gy * 15, gz * 15, 3);
    var rift = l > -15 && l < 82 ? Math.exp(-Math.pow((b - 1.4 - 0.025 * l) / 2.4, 2)) : 0;
    var dim = (1 - 0.8 * rift * smoothstep(0.3, 0.6, dust)) *
              (1 - 0.55 * Math.exp(-ab / 3.5) * smoothstep(0.5, 0.75, dust));
    disc *= (0.35 + 1.3 * clumps * clumps) * dim;
    bulge *= (0.7 + 0.6 * clumps) * dim;
    return [disc, bulge];
  }

  /* Star colour from B-V, a little paler than a true black body, as the eye sees them. */
  var STAR_COLOURS = [[-0.4, 165, 190, 255], [0, 208, 220, 255], [0.35, 246, 246, 255],
                      [0.6, 255, 243, 228], [1.0, 255, 224, 192], [1.5, 255, 200, 148],
                      [2.0, 255, 182, 124]];

  function starColour(bv) {
    var s = STAR_COLOURS, i = 0;
    if (bv <= s[0][0]) return s[0].slice(1);
    while (i < s.length - 2 && bv > s[i + 1][0]) i++;
    var a = s[i], b = s[i + 1], t = clamp01((bv - a[0]) / (b[0] - a[0]));
    return [Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t),
            Math.round(a[3] + (b[3] - a[3]) * t)];
  }

  /* --------------------------------------------------------------------------- data */

  function decodeLine(flat, scale) {
    var pts = new Array(flat.length / 2), x = 0, y = 0;
    for (var i = 0; i < flat.length; i += 2) {
      x += flat[i]; y += flat[i + 1];
      pts[i / 2] = [x * scale, y * scale];
    }
    return pts;
  }

  function decodeArcs(world) {
    return world.arcs.map(function (flat) { return decodeLine(flat, world.scale); });
  }

  function ringCoords(ids, arcs) {
    var out = [];
    ids.forEach(function (id, i) {
      var seg = id >= 0 ? arcs[id] : arcs[~id].slice().reverse();
      for (var j = i ? 1 : 0; j < seg.length; j++) out.push(seg[j]);
    });
    return out;
  }

  function multi(polys, arcs) {
    return { type: 'MultiPolygon',
             coordinates: polys.map(function (p) {
               return p.map(function (r) { return ringCoords(r, arcs); });
             }) };
  }

  function unit(lon, lat, out, i) {
    var l = lon * RAD, p = lat * RAD, c = Math.cos(p);
    out[i] = c * Math.cos(l); out[i + 1] = c * Math.sin(l); out[i + 2] = Math.sin(p);
  }

  /* ------------------------------------------------------------------------ the page */

  function start(world, earth, regions) {
    var stage = el('stage'), under = el('under'), canvas = el('earth'), over = el('over');
    var ctx = canvas.getContext('2d'), uctx = under.getContext('2d'), octx = over.getContext('2d');
    var card = el('card'), readout = el('readout'), worldLabel = el('world-label');
    var sky = el('sky'), sctx = sky ? sky.getContext('2d') : null;

    var root = document.documentElement, T = THEMES.light, ramp = null, paperURL = null;
    var stars = null, starsAsked = false;

    /* The paper's grain by day; by night the sky canvas is the background. */
    function setTheme() {
      T = THEMES[root.getAttribute('data-theme') === 'dark' && sctx ? 'dark' : 'light'];
      ramp = buildRamp(T.ramp);
      if (!T.dark && !paperURL) paperURL = 'url(' + paperTile().toDataURL() + ')';
      document.body.style.backgroundImage = T.dark ? 'none' : paperURL;
      canvas.setAttribute('aria-label', T.dark
        ? 'The Earth at night from space, just after sunset. Countries processed with EarthPV are outlined in light and lit, with their solar capacity glowing from red to gold; the country links below the globe open each atlas.'
        : 'An ink sketch of the Earth. Countries processed with EarthPV are outlined in ink and left white, with their solar capacity in red; the country links below the globe open each atlas.');
      if (T.dark && !starsAsked) {
        starsAsked = true;
        json('stars.json').then(function (doc) {
          stars = decodeStars(doc);
          if (T.dark) drawSky();
        }).catch(function (err) {
          if (window.console) console.warn('Electrify Earth: no stars,', err);
        });
      }
    }
    setTheme();

    var W = 0, H = 0, DPR = 1, cx = 0, cy = 0, R = 1, ringR = 1, S = 1;
    var quality = 2;
    var rot = START.slice();
    var projection = d3.geoOrthographic().clipAngle(90).precision(0.6);
    var path = d3.geoPath(projection, ctx);

    var arcs = decodeArcs(world);
    var atlasByName = {};
    earth.atlases.forEach(function (a) {
      a.partSet = new Set(a.parts);
      atlasByName[a.name] = a;
    });

    var features = world.features.map(function (f) {
      var feature = { type: 'Feature', properties: {}, geometry: multi(f.p, arcs) };
      return { name: f.n, iso: f.i, box: f.b, polys: f.p, feature: feature,
               bounds: d3.geoBounds(feature), atlas: atlasByName[f.n] || null };
    });
    var featureByName = {};
    features.forEach(function (f) { featureByName[f.name] = f; });

    /* The United States and China are too large for one atlas on one PC, so they are drawn
       and picked state by state. Without this file they simply stay whole countries. */
    var inkedRegionPolys = [];
    if (regions) {
      regions.regions.forEach(function (r) {
        var polys = r.p.map(function (poly) {
          return poly.map(function (flat) { return decodeLine(flat, regions.scale); });
        });
        var item = { name: r.n, kind: r.t, iso: r.i, box: r.b, division: r.d, rings: polys,
                     feature: { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: polys } },
                     atlas: atlasByName[r.n] || null };
        var country = featureByName[r.c];
        (country.regions = country.regions || []).push(item);
        featureByName[r.n] = item;
        if (item.atlas) inkedRegionPolys = inkedRegionPolys.concat(polys);
      });
    }
    var inkedRegions = inkedRegionPolys.length ? { type: 'MultiPolygon', coordinates: inkedRegionPolys } : null;

    /* What is inked and what stays pencil, polygon by polygon: France's atlas never imaged
       French Guiana, so that polygon stays pencil while still clicking through to France. */
    var pencilPolys = [], inkedPolys = [];
    features.forEach(function (f) {
      f.polys.forEach(function (p, i) {
        (f.atlas && f.atlas.partSet.has(i) ? inkedPolys : pencilPolys).push(p);
      });
    });
    /* The washes need no coastline of their own (the brush draws that), so they fill a
       third of the points. Thinned arc by arc, keeping each arc's ends, so neighbours still
       share one border and a long straight border keeps its corners. A ring that would
       turn inside out keeps all of its points. */
    var coarseArcs = arcs.map(function (pts) {
      if (pts.length <= 7) return pts;
      var out = [];
      for (var i = 0; i < pts.length - 1; i += 3) out.push(pts[i]);
      out.push(pts[pts.length - 1]);
      return out;
    });
    function coarse(polys) {
      return { type: 'Feature', properties: {}, geometry: {
        type: 'MultiPolygon',
        coordinates: polys.map(function (p) {
          return p.map(function (r, index) {
            var ring = ringCoords(r, coarseArcs);
            if (index === 0 && d3.geoArea({ type: 'Polygon', coordinates: [ring] }) > 6) {
              return ringCoords(r, arcs);
            }
            return ring;
          });
        }) } };
    }
    var pencil = coarse(pencilPolys);
    var inked = coarse(inkedPolys);

    /* ---------------------------------------------------------------- line work */
    var lineSets = { grat: [], hatch: [], pencilBorder: [], regionBorder: [], pencilCoast: [], pencilGhost: [], ink: [], inkGhost: [] };

    (function buildLines() {
      var uses = new Uint8Array(arcs.length), inkUse = new Uint8Array(arcs.length);
      features.forEach(function (f) {
        f.polys.forEach(function (poly, i) {
          var isInk = f.atlas && f.atlas.partSet.has(i);
          poly.forEach(function (r) {
            r.forEach(function (a) {
              var k = a < 0 ? ~a : a;
              uses[k]++;
              if (isInk) inkUse[k] = 1;
            });
          });
        });
      });
      var rand = mulberry(20261108);

      function make(pts, wobble, period) {
        var n = pts.length, xyz = new Float32Array(n * 3);
        var wx = wobble ? pressure(n, rand, 7) : null, wy = wobble ? pressure(n, rand, 7) : null;
        for (var i = 0; i < n; i++) {
          var lat = pts[i][1], lon = pts[i][0];
          if (wobble) {
            lat += (wy[i] - 0.5) * wobble;
            lon += (wx[i] - 0.5) * wobble / Math.max(0.2, Math.cos(lat * RAD));
          }
          unit(lon, lat, xyz, i * 3);
        }
        return { n: n, xyz: xyz, w: pressure(n, rand, period) };
      }

      arcs.forEach(function (pts, k) {
        if (inkUse[k]) {
          lineSets.ink.push(make(pts, 0, 16));
          lineSets.inkGhost.push(make(pts, 0.55, 9));
        } else if (uses[k] >= 2) {
          lineSets.pencilBorder.push(make(pts, 0.22, 11));
        } else {
          lineSets.pencilCoast.push(make(pts, 0.14, 13));
          lineSets.pencilGhost.push(make(pts, 0.6, 9));
        }
      });

      if (regions) {
        regions.lines.forEach(function (flat) {
          lineSets.regionBorder.push(make(decodeLine(flat, regions.scale), 0.1, 11));
        });
      }
      inkedRegionPolys.forEach(function (poly) {
        lineSets.ink.push(make(poly[0], 0, 16));
        lineSets.inkGhost.push(make(poly[0], 0.55, 9));
      });

      var lon, lat, pts;
      for (lon = -180; lon < 180; lon += 30) {
        pts = [];
        for (lat = -80; lat <= 80; lat += 2.5) pts.push([lon, lat]);
        lineSets.grat.push(make(pts, 0.5, 18));
      }
      for (lat = -60; lat <= 60; lat += 30) {
        pts = [];
        for (lon = -180; lon <= 180; lon += 2.5) pts.push([lon, lat]);
        lineSets.grat.push(make(pts, 0.5, 18));
      }

      /* Pencil shading, drawn on the land so that it turns with it: circles round one
         tilted axis, kept wherever a map of the pencil land says they are ashore. Lines
         round the Earth's own axis would crowd together towards the poles; these are evenly
         spaced everywhere and close up only at the axis's two ends, both in open ocean. */
      var mapW = 2160, mapH = 1080, map = document.createElement('canvas');
      map.width = mapW; map.height = mapH;
      var mapCtx = map.getContext('2d', { willReadFrequently: true });
      var mapPath = d3.geoPath(d3.geoEquirectangular().scale(mapW / TAU).translate([mapW / 2, mapH / 2]), mapCtx);
      mapCtx.beginPath();
      mapPath(pencil);
      mapCtx.fill();
      if (inkedRegions) {       // a state with an atlas leaves the rest of its country in pencil
        mapCtx.globalCompositeOperation = 'destination-out';
        mapCtx.beginPath();
        mapPath(inkedRegions);
        mapCtx.fill();
      }
      var land = mapCtx.getImageData(0, 0, mapW, mapH).data;
      function ashore(lo, la) {
        var mx = Math.min(mapW - 1, Math.floor((lo + 180) / 360 * mapW));
        var my = Math.min(mapH - 1, Math.floor((90 - la) / 180 * mapH));
        return land[(my * mapW + mx) * 4 + 3] > 127;
      }
      function flushHatch(run) {
        if (run.length >= 2) lineSets.hatch.push(make(run, 0.08, 5));
      }
      var ax = new Float64Array(3);
      unit(HATCH_POLE[0], HATCH_POLE[1], ax, 0);
      var ul = Math.hypot(ax[1], ax[0]), ux = -ax[1] / ul, uy = ax[0] / ul;   // across the axis
      var vx = ax[1] * 0 - ax[2] * uy, vy = ax[2] * ux - ax[0] * 0, vz = ax[0] * uy - ax[1] * ux;
      for (var theta = HATCH_DEG; theta < 180; theta += HATCH_DEG) {
        var ct = Math.cos(theta * RAD), st = Math.sin(theta * RAD), run = [];
        var dphi = HATCH_STEP / Math.max(0.05, st);
        for (var phi = 0; phi < 360; phi += dphi) {
          var cf = st * Math.cos(phi * RAD), sf = st * Math.sin(phi * RAD);
          var hx = ct * ax[0] + cf * ux + sf * vx;
          var hy = ct * ax[1] + cf * uy + sf * vy;
          var hz = ct * ax[2] + sf * vz;
          lon = Math.atan2(hy, hx) / RAD;
          lat = Math.asin(Math.max(-1, Math.min(1, hz))) / RAD;
          if (ashore(lon, lat)) {
            run.push([lon, lat]);
          } else {
            flushHatch(run);
            run = [];
          }
        }
        flushHatch(run);
      }
    })();

    /* ----------------------------------------------------- the atlases' own cells */
    var step = earth.bin_deg;
    var seen = [], pv = [];
    earth.processed.forEach(function (row) {
      var lat = (row[0] + 0.5) * step;
      for (var i = 1; i < row.length; i += 2) {
        for (var k = 0; k < row[i + 1]; k++) seen.push([(row[i] + k + 0.5) * step, lat]);
      }
    });
    earth.pv.forEach(function (row) {
      var lat = (row[0] + 0.5) * step, lon = 0;
      for (var i = 1; i < row.length; i += 2) {
        lon += row[i];
        pv.push([(lon + 0.5) * step, lat, row[i + 1]]);
      }
    });
    pv.sort(function (a, b) { return a[2] - b[2]; });   // the brush reaches the largest last

    var seenXYZ = new Float32Array(seen.length * 3);
    seen.forEach(function (p, i) { unit(p[0], p[1], seenXYZ, i * 3); });
    var pvXYZ = new Float32Array(pv.length * 3), pvMW = new Float32Array(pv.length);
    pv.forEach(function (p, i) { unit(p[0], p[1], pvXYZ, i * 3); pvMW[i] = p[2]; });

    /* A 0.1 degree cell is about a pixel at this size, so the cells are laid down pixel by
       pixel: as dots they would only cover each other. Each cell is shared among the four
       pixels around it, which keeps it steady as the globe turns. */
    var raster = document.createElement('canvas'), rasterCtx = raster.getContext('2d');
    var rImage, rPixels, rTone, rMW, rMark, rSize = 0, rLeft = 0, rTop = 0, rCell = 1;
    var rTouched = new Int32Array((seen.length + pv.length) * 4), rCount = 0;

    /* From a blush on the white land to full vermilion, over a log scale of MW in one cell
       (by night from ember to gold: THEMES' `ramp`). Opaque: the land under a cell with
       solar is white whatever the wash beneath it. */
    var LOG_LOW = -2, LOG_HIGH = Math.log(RED_MW) / Math.LN10;

    function rasterSetup() {
      var margin = 2;
      rSize = Math.ceil(2 * (R + margin) * DPR);
      rLeft = Math.round((cx - R - margin) * DPR);
      rTop = Math.round((cy - R - margin) * DPR);
      raster.width = raster.height = rSize;
      rImage = rasterCtx.createImageData(rSize, rSize);
      rPixels = new Uint32Array(rImage.data.buffer);
      rTone = new Float32Array(rSize * rSize);
      rMW = new Float32Array(rSize * rSize);
      rMark = new Uint8Array(rSize * rSize);
      rCell = step * RAD * R * DPR;
    }

    function touch(buf, o, v) {
      buf[o] += v;
      if (!rMark[o]) { rMark[o] = 1; rTouched[rCount++] = o; }
    }

    function deposit(buf, px, py, v) {
      var ix = Math.floor(px), iy = Math.floor(py);
      if (ix < 0 || iy < 0 || ix >= rSize - 1 || iy >= rSize - 1) return;
      var fx = px - ix, fy = py - iy, o = iy * rSize + ix;
      touch(buf, o, v * (1 - fx) * (1 - fy));
      touch(buf, o + 1, v * fx * (1 - fy));
      touch(buf, o + rSize, v * (1 - fx) * fy);
      touch(buf, o + rSize + 1, v * fx * fy);
    }

    /* ------------------------------------------------------------------- drawing */
    var cl, sl, cp, sp, cg, sg;

    function setRotation() {
      cl = Math.cos(rot[0] * RAD); sl = Math.sin(rot[0] * RAD);
      cp = Math.cos(rot[1] * RAD); sp = Math.sin(rot[1] * RAD);
      cg = Math.cos(rot[2] * RAD); sg = Math.sin(rot[2] * RAD);
      projection.rotate(rot);
    }

    /* Stroke a set of lines in width buckets. `lift` is the pressure below which the
       brush leaves the paper; widths thin towards the limb. */
    function strokeSet(set, widths, alpha, color, lift) {
      var nb = widths.length, paths = new Array(nb), b, i;
      for (b = 0; b < nb; b++) paths[b] = new Path2D();
      for (var s = 0; s < set.length; s++) {
        var line = set[s], xyz = line.xyz, w = line.w, n = line.n;
        var has = false, px = 0, py = 0;
        for (i = 0; i < n; i++) {
          var j = i * 3, x = xyz[j], y = xyz[j + 1], z = xyz[j + 2];
          var x1 = x * cl - y * sl, y1 = x * sl + y * cl;
          var k = z * cp + x1 * sp, X = x1 * cp - z * sp;
          if (X <= 0) { has = false; continue; }
          var Y = y1 * cg - k * sg, Z = k * cg + y1 * sg;
          var sx = cx + R * Y, sy = cy - R * Z;
          if (has && w[i] >= lift) {
            var v = (w[i] - lift) / (1 - lift);
            v = v * v;
            b = Math.min(nb - 1, Math.floor(v * nb * (X < 0.35 ? 0.55 : 1)));
            paths[b].moveTo(px, py);
            paths[b].lineTo(sx, sy);
          }
          has = true; px = sx; py = sy;
        }
      }
      ctx.lineCap = 'round';
      ctx.strokeStyle = 'rgba(' + color + ',' + alpha + ')';
      for (b = 0; b < nb; b++) {
        ctx.lineWidth = widths[b] * S;
        ctx.stroke(paths[b]);
      }
    }

    function drawCells(ink) {
      var i, j, x, y, z, x1, y1, k, X, Y, Z, n, o;
      /* Under a pixel per cell, a pixel shows the mean of the cells it holds. X undoes the
         crowding towards the limb, so a country reads the same wherever it is on the globe. */
      var share = Math.min(1, rCell * rCell);
      rCount = 0;

      /* White under every cell the model has looked at, so that the red stands out. */
      n = Math.floor(seen.length * ink);
      for (i = 0; i < n; i++) {
        j = i * 3; x = seenXYZ[j]; y = seenXYZ[j + 1]; z = seenXYZ[j + 2];
        x1 = x * cl - y * sl; y1 = x * sl + y * cl;
        k = z * cp + x1 * sp; X = x1 * cp - z * sp;
        if (X <= 0) continue;
        Y = y1 * cg - k * sg; Z = k * cg + y1 * sg;
        deposit(rTone, (cx + R * Y) * DPR - rLeft - 0.5, (cy - R * Z) * DPR - rTop - 0.5, share * X);
      }

      /* Capacity, cell by cell. The largest also get a mark of their own, its area
         proportional to MWp, so one great park still shows on a screen of coarse pixels. */
      var red = new Path2D(), halo = T.halo ? new Path2D() : null;
      n = Math.floor(pv.length * ink);
      for (i = 0; i < n; i++) {
        j = i * 3; x = pvXYZ[j]; y = pvXYZ[j + 1]; z = pvXYZ[j + 2];
        x1 = x * cl - y * sl; y1 = x * sl + y * cl;
        k = z * cp + x1 * sp; X = x1 * cp - z * sp;
        if (X <= 0) continue;
        Y = y1 * cg - k * sg; Z = k * cg + y1 * sg;
        var mw = pvMW[i], px = cx + R * Y, py = cy - R * Z;
        deposit(rMW, px * DPR - rLeft - 0.5, py * DPR - rTop - 0.5, mw * share * X);
        if (mw >= RED_MW) {
          var r = Math.max(0.5, Math.min(2.6, 0.055 * Math.sqrt(mw))) * S * (0.4 + 0.6 * X);
          red.moveTo(px + r, py);
          red.arc(px, py, r, 0, TAU);
          if (halo) {
            halo.moveTo(px + r * 2.8, py);
            halo.arc(px, py, r * 2.8, 0, TAU);
          }
        }
      }

      var tone = T.tone, toneWord = (tone[2] << 16) | (tone[1] << 8) | tone[0], toneA = T.toneAlpha;
      for (i = 0; i < rCount; i++) {
        o = rTouched[i];
        if (rMW[o] > 0) {
          var u = (Math.log(rMW[o]) / Math.LN10 - LOG_LOW) / (LOG_HIGH - LOG_LOW);
          rPixels[o] = ramp[u <= 0 ? 0 : u >= 1 ? 255 : Math.round(u * 255)];
        } else {
          rPixels[o] = ((Math.min(1, rTone[o] * 1.3) * toneA * 255) << 24) | toneWord;
        }
      }
      rasterCtx.putImageData(rImage, 0, 0);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(raster, rLeft, rTop);
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      for (i = 0; i < rCount; i++) {
        o = rTouched[i];
        rPixels[o] = 0; rTone[o] = 0; rMW[o] = 0; rMark[o] = 0;
      }

      if (halo) {
        ctx.fillStyle = rgba(T.halo);
        ctx.fill(halo);
      }
      ctx.fillStyle = rgba(T.mark);
      ctx.fill(red);
    }

    var hovered = null, intro = REDUCED ? 1 : 0;

    function draw() {
      setRotation();
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.clearRect(0, 0, W, H);
      var ink = Math.min(1, intro * 1.15);

      /* Pencil land: a faint wash and hatching. */
      ctx.beginPath();
      path(pencil);
      ctx.fillStyle = rgba(T.wash);
      ctx.fill();
      strokeSet(lineSets.hatch, [0.35, 0.55, 0.8], T.hatch[1], T.hatch[0], 0.16);

      strokeSet(lineSets.grat, [0.5], T.grat[1], T.grat[0], 0.3);
      strokeSet(lineSets.pencilBorder, [0.45, 0.7], T.border[1], T.border[0], 0.1);
      strokeSet(lineSets.regionBorder, [0.35, 0.55], T.region[1], T.region[0], 0.1);
      if (quality > 0) strokeSet(lineSets.pencilGhost, [0.4, 0.6], T.ghost[1], T.ghost[0], 0.3);
      strokeSet(lineSets.pencilCoast, [0.5, 0.75, 1.05], T.coast[1], T.coast[0], 0.08);

      /* A country with an atlas: only a trace of wash, for whatever its atlas did not image.
         What it did image is laid over this in white. */
      ctx.beginPath();
      path(inked);
      if (inkedRegions) path(inkedRegions);
      ctx.fillStyle = 'rgba(' + T.inkWash[0] + ',' + (T.inkWash[1] * ink) + ')';
      ctx.fill();

      if (hovered && !hovered.atlas) {
        ctx.beginPath();
        path(hovered.feature);
        ctx.fillStyle = 'rgba(' + T.red + ',.14)';
        ctx.fill();
      }

      drawCells(ink);

      if (quality > 0) strokeSet(lineSets.inkGhost, [0.4, 0.7], T.inkGhost[1] * ink, T.inkGhost[0], 0.2);
      strokeSet(lineSets.ink, [0.55, 0.8, 1.1, 1.5, 2], T.ink[1] * ink, T.ink[0], 0);

      if (hovered) {
        ctx.beginPath();
        path(hovered.feature);
        ctx.strokeStyle = 'rgba(' + T.red + ',.95)';
        ctx.lineWidth = 1.7 * S;
        ctx.lineJoin = 'round';
        ctx.stroke();
      }
    }

    /* ---------------------------------------------- the sphere and the pencil ring */
    var share = earth.best_mwp / 1000 / earth.world.gw;
    var verifiedShare = earth.verified_mwp / 1000 / earth.world.gw;
    var TOP = -Math.PI / 2;

    function brushDisc(c, rIn, widthAt, color) {
      /* A thin ring of varying width, as one filled shape. */
      var rand2 = mulberry(4), n = 720, pts = pressure(n + 1, rand2, 26), i, a;
      c.beginPath();
      for (i = 0; i <= n; i++) {
        a = i / n * TAU;
        var o = rIn + (pts[i] - 0.5) * 0.7 + widthAt(a, pts[i]);
        c[i ? 'lineTo' : 'moveTo'](cx + Math.cos(a) * o, cy + Math.sin(a) * o);
      }
      for (i = n; i >= 0; i--) {
        a = i / n * TAU;
        var r2 = rIn + (pts[i] - 0.5) * 0.7;
        c.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
      }
      c.closePath();
      c.fillStyle = color;
      c.fill();
    }

    /* The night side of the Earth and the air round its limb, pixel by pixel, once per size:
       the Sun has just set behind the limb at SUN_PSI, so the air there still glows in
       sunset bands (orange low down, gold, then blue), and the rest of the limb shows only a
       faint blue rim and the thin green line of the airglow, about 100 km up. Heights are
       exaggerated about threefold so that the bands read at this size. Each band is a
       profile in height times a profile in angle from the Sun, both from tables. */
    var ATMO_EXT = 1.17;

    function atmosphereProfiles(RD) {
      var steps = Math.ceil(ATMO_EXT * RD * 4) + 2, k, i;
      var radial = [], angular = [];
      function table(n, f) {
        var t = new Float32Array(n);
        for (i = 0; i < n; i++) t[i] = f(i);
        return t;
      }
      function sq(x) { return x * x; }
      /* Outside the limb, by height h in globe radii. */
      var hOut = [
        function (h) { return Math.exp(-h / 0.013); },                       // orange, low air
        function (h) { return Math.exp(-sq((h - 0.008) / 0.009)); },        // gold
        function (h) { return Math.exp(-sq((h - 0.017) / 0.012)); },        // blue
        function (h) { return Math.exp(-sq((h - 0.042) / 0.005)); },        // airglow
        function (h) { return Math.exp(-h / 0.07); },                        // forward scatter
        function (h) { return Math.exp(-h / 0.13); }                         // violet
      ];
      /* Inside, by depth t below the limb: air in front of the ground, and the dusk on it. */
      var hIn = [
        function (t) { return Math.exp(-t / 0.009); },
        function (t) { return Math.exp(-t / 0.006); },
        function (t) { return Math.exp(-t / 0.02); },
        function (t) { return 0; },
        function (t) { return Math.exp(-t / 0.055); },
        function (t) { return 0; }
      ];
      for (k = 0; k < hOut.length; k++) {
        radial.push(table(steps, (function (fo, fi) {
          return function (j) {
            var q = j / 4 / RD;
            return q >= 1 ? fo(q - 1) : fi(1 - q);
          };
        })(hOut[k], hIn[k])));
      }
      /* By s = 1 - cos(angle from the Sun), 0 to 2. */
      var sFn = [
        function (s) { return Math.exp(-s / 0.075); },
        function (s) { return Math.exp(-s / 0.04); },
        function (s) { return 0.09 + 0.55 * Math.exp(-s / 0.4); },
        function (s) { return 1 - 0.85 * Math.exp(-s / 0.3); },
        function (s) { return Math.exp(-s / 0.13); },
        function (s) { return Math.exp(-s / 0.5); }
      ];
      for (k = 0; k < sFn.length; k++) {
        angular.push(table(1025, (function (f) { return function (j) { return f(j / 512); }; })(sFn[k])));
      }
      return { radial: radial, angular: angular };
    }

    /* Colour and strength of each band; inside the limb the scatter term is the dusk. */
    var ATMO_BANDS = [[255, 92, 36, 1.1], [255, 190, 96, 0.55], [72, 128, 255, 0.9],
                      [96, 238, 156, 0.34], [255, 120, 86, 0.34], [130, 84, 204, 0.24]];
    var ATMO_IN = [[255, 98, 44, 0.9], [255, 190, 110, 0.5], [44, 86, 178, 0.6], [0, 0, 0, 0],
                   [150, 52, 44, 0.62], [0, 0, 0, 0]];

    /* The ground well inside the limb is a plain gradient; only the ring from ATMO_INNER out
       is shaded pixel by pixel, into its own canvas, laid over that gradient. */
    var ATMO_INNER = 0.78;

    function groundRGB(q) {
      var qq = q * q;
      return [12 - 6 * qq, 23 - 12 * qq, 46 - 20 * qq];
    }

    function drawAtmosphere(c) {
      var g = c.createRadialGradient(cx, cy, 0, cx, cy, R);
      for (var gi = 0; gi <= 10; gi++) g.addColorStop(gi / 10, 'rgb(' + groundRGB(gi / 10).join(',') + ')');
      c.fillStyle = g;
      c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();

      var RD = R * DPR, half = Math.ceil(ATMO_EXT * RD) + 1, size = half * 2;
      var x0 = Math.round(cx * DPR) - half, y0 = Math.round(cy * DPR) - half;
      var ox = cx * DPR - x0, oy = cy * DPR - y0;
      var ring = document.createElement('canvas');
      ring.width = ring.height = size;
      var rctx = ring.getContext('2d'), img = rctx.createImageData(size, size), d = img.data;
      var P = atmosphereProfiles(RD), rad = P.radial, ang = P.angular, nb = ATMO_BANDS.length;
      var sx = Math.cos(SUN_PSI), sy = -Math.sin(SUN_PSI);
      var lim = ATMO_EXT * RD, inner = ATMO_INNER * RD, rand = mulberry(31);
      for (var py = 0; py < size; py++) {
        var dy = py + 0.5 - oy;
        if (Math.abs(dy) > lim) continue;
        var outer = Math.sqrt(lim * lim - dy * dy);
        var hole = Math.abs(dy) < inner ? Math.sqrt(inner * inner - dy * dy) : -1;
        var from = Math.max(0, Math.floor(ox - outer)), to = Math.min(size - 1, Math.ceil(ox + outer));
        for (var px = from; px <= to; px++) {
          var dx = px + 0.5 - ox;
          if (dx > -hole && dx < hole) { px = Math.floor(ox + hole); continue; }
          var r = Math.sqrt(dx * dx + dy * dy);
          if (r > lim || r < inner) continue;
          var o = (py * size + px) * 4, q = r / RD;
          var si = Math.round((1 - (dx * sx + dy * sy) / r) * 512);
          var ri = Math.round(r * 4), k, w, band;
          var dither = rand() - 0.5;
          /* The air outside the limb, as added light. */
          var lr = 0, lg = 0, lb = 0;
          if (r > RD - 1) {
            for (k = 0; k < nb; k++) {
              band = ATMO_BANDS[k];
              w = rad[k][ri] * ang[k][si] * band[3];
              lr += band[0] * w; lg += band[1] * w; lb += band[2] * w;
            }
          }
          /* The ground: deep night blue, with the air and the dusk over it near the limb,
             faded in from the gradient's edge. Opaque, so no star shows through the Earth. */
          var gr = 0, gg = 0, gb = 0;
          if (r < RD + 1) {
            var base = groundRGB(q), feather = smoothstep(ATMO_INNER, ATMO_INNER + 0.06, q);
            gr = base[0]; gg = base[1]; gb = base[2];
            for (k = 0; k < nb; k++) {
              band = ATMO_IN[k];
              if (!band[3]) continue;
              w = rad[k][ri] * ang[k][si] * band[3] * feather;
              gr += band[0] * w; gg += band[1] * w; gb += band[2] * w;
            }
          }
          var cover = clamp01(RD - r + 0.5);
          var la = Math.min(1, Math.max(lr, lg, lb) / 255);
          var alpha = cover + (1 - cover) * la;
          if (alpha <= 0) continue;
          /* Premultiplied mix of the opaque ground and the light, back to straight colour. */
          var outR = cover * Math.min(255, gr) + (1 - cover) * Math.min(255, lr);
          var outG = cover * Math.min(255, gg) + (1 - cover) * Math.min(255, lg);
          var outB = cover * Math.min(255, gb) + (1 - cover) * Math.min(255, lb);
          d[o] = outR / alpha + dither; d[o + 1] = outG / alpha + dither;
          d[o + 2] = outB / alpha + dither; d[o + 3] = alpha * 255 + 0.5;
        }
      }
      rctx.putImageData(img, 0, 0);
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.drawImage(ring, x0, y0);
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
    }

    function drawUnder() {
      var c = uctx;
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
      c.clearRect(0, 0, W, H);

      if (T.dark) {
        drawAtmosphere(c);
      } else {
        /* Opaque, so that the sheet's fibres do not show through land turning over them. */
        c.fillStyle = '#f8f4ec';
        c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();

        /* The sphere: a little brighter than the sheet, darkening at the limb. */
        var g = c.createRadialGradient(cx, cy, R * 0.1, cx, cy, R);
        g.addColorStop(0, 'rgba(255,253,248,.22)');
        g.addColorStop(0.75, 'rgba(255,253,248,.05)');
        g.addColorStop(0.93, 'rgba(60,52,42,.03)');
        g.addColorStop(1, 'rgba(60,52,42,.11)');
        c.fillStyle = g;
        c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();

        /* The sphere's own outline, thin on the lit side. */
        brushDisc(c, R, function (a, p) {
          var side = 0.5 + 0.5 * Math.cos(a - 0.85);
          return (0.5 + 2.1 * side * side + p * 0.7) * S;
        }, 'rgba(' + INK + ',.88)');
      }

      /* The pencil ring: the whole world's PV, still to be drawn over. */
      c.lineCap = 'round';
      var rand3 = mulberry(12);
      for (var pass = 0; pass < 2; pass++) {
        var n = 1400, wob = pressure(n + 1, rand3, 60), lift = pressure(n + 1, rand3, 20);
        c.beginPath();
        var pen = false;
        for (var i = 0; i <= n; i++) {
          var a = TOP + i / n * TAU;
          var r = ringR + (wob[i] - 0.5) * 3.2 * S + pass * 1.1;
          var sx = cx + Math.cos(a) * r, sy = cy + Math.sin(a) * r;
          if (lift[i] < 0.14) { pen = false; continue; }
          c[pen ? 'lineTo' : 'moveTo'](sx, sy);
          pen = true;
        }
        c.strokeStyle = 'rgba(' + T.ring[0] + ',' + (pass ? T.ring[2] : T.ring[1]) + ')';
        c.lineWidth = (pass ? 0.5 : 0.8) * S;
        c.stroke();
      }

      /* A scale in GW round the ring. */
      c.font = (11 * Math.max(0.85, Math.min(1.15, S))) + 'px ' + SERIF;
      c.textAlign = 'center'; c.textBaseline = 'middle';
      for (var gw = 500; gw < earth.world.gw; gw += 500) {
        var ta = TOP + gw / earth.world.gw * TAU;
        var ca = Math.cos(ta), sa = Math.sin(ta);
        c.beginPath();
        c.moveTo(cx + ca * (ringR - 3 * S), cy + sa * (ringR - 3 * S));
        c.lineTo(cx + ca * (ringR + 7 * S), cy + sa * (ringR + 7 * S));
        c.strokeStyle = rgba(T.tick);
        c.lineWidth = 0.9 * S;
        c.stroke();
        c.fillStyle = rgba(T.label);
        c.fillText(gw.toLocaleString('en-US') + (gw === 500 ? ' GW' : ''), cx + ca * (ringR + 21 * S), cy + sa * (ringR + 21 * S));
      }
    }

    /* The night sky behind the page, once per size: the camera's view past the Earth, the
       Sun just hidden behind it (skyFrame). The diffuse light (the sunset's afterglow
       round the Sun, a faint blue haze round the Earth, the Milky Way, the zodiacal light
       along the ecliptic) is shaded at about half the page's resolution and scaled up; the
       stars are then drawn one by one at full resolution. */
    var skyTimer = 0, skyDone = false, skyBase = null;

    function scheduleSky() {
      clearTimeout(skyTimer);
      if (!T.dark || !sctx) return;
      skyTimer = setTimeout(drawSky, skyDone ? 150 : 0);
    }

    function drawSky() {
      if (!T.dark || !sctx || !W) return;      // not before the first layout
      skyDone = true;
      var box = sky.getBoundingClientRect(), sbox = stage.getBoundingClientRect();
      if (!box.width || !box.height) return;
      var sun = sunToday(new Date()), F = skyFrame(sun.dir);
      var v = { SW: box.width, SH: box.height, gx: sbox.left - box.left + cx, gy: sbox.top - box.top + cy,
                A: F.A, U: F.U, X: F.X, S: sun.dir, f: R / Math.tan(EARTH_DEG * RAD),
                ce: Math.cos(sun.eps), se: Math.sin(sun.eps) };
      var sd = Math.min(window.devicePixelRatio || 1, 2);
      if (v.SW * v.SH * sd * sd > 9e6) sd = Math.sqrt(9e6 / (v.SW * v.SH));
      sky.width = Math.round(v.SW * sd);
      sky.height = Math.round(v.SH * sd);

      /* The diffuse light is kept, so the stars arriving later do not shade it again. */
      var key = [v.SW, v.SH, v.gx, v.gy, R, new Date().toDateString()].join();
      if (!skyBase || skyBase.key !== key) skyBase = { key: key, canvas: diffuseSky(v) };
      sctx.setTransform(1, 0, 0, 1, 0, 0);
      sctx.imageSmoothingEnabled = true;
      sctx.imageSmoothingQuality = 'high';
      sctx.drawImage(skyBase.canvas, 0, 0, sky.width, sky.height);
      if (stars) {
        sctx.setTransform(sd, 0, 0, sd, 0, 0);
        drawStars(v);
      }
    }

    function diffuseSky(v) {
      var A = v.A, U = v.U, X = v.X, Sd = v.S, f = v.f, SW = v.SW, SH = v.SH;
      var k = Math.min(0.34, Math.sqrt(200000 / (SW * SH)));
      var lw = Math.max(2, Math.round(SW * k)), lh = Math.max(2, Math.round(SH * k));
      var low = document.createElement('canvas');
      low.width = lw; low.height = lh;
      var lctx = low.getContext('2d'), img = lctx.createImageData(lw, lh), d = img.data;
      var rand = mulberry(5);
      for (var row = 0; row < lh; row++) {
        var dy = v.gy - (row + 0.5) * SH / lh;
        for (var col = 0; col < lw; col++) {
          var dx = (col + 0.5) * SW / lw - v.gx;
          var x = A[0] * f + X[0] * dx + U[0] * dy;
          var y = A[1] * f + X[1] * dx + U[1] * dy;
          var z = A[2] * f + X[2] * dx + U[2] * dy;
          var l = Math.sqrt(x * x + y * y + z * z);
          x /= l; y /= l; z /= l;
          var q = Math.sqrt(dx * dx + dy * dy) / R;
          var th = Math.acos(Math.max(-1, Math.min(1, x * Sd[0] + y * Sd[1] + z * Sd[2]))) / RAD;
          /* Space, a little less black towards the Earth. */
          var near = Math.exp(-Math.max(0, q - 1) / 1.4), haze = Math.exp(-Math.max(0, q - 1) / 0.22);
          var r = 3 + 5 * near + 10 * haze, g = 4 + 7 * near + 16 * haze, b = 11 + 15 * near + 38 * haze;
          /* The afterglow: orange right by the hidden Sun, rose, then violet. */
          var w1 = Math.exp(-th / 3.2) * 0.62, w2 = Math.exp(-th / 8.5) * 0.3, w3 = Math.exp(-th / 21) * 0.3;
          r += 255 * w1 + 226 * w2 + 92 * w3;
          g += 146 * w1 + 92 * w2 + 58 * w3;
          b += 78 * w1 + 106 * w2 + 152 * w3;
          /* The Milky Way. */
          var mw = milkyWay(GAL[0][0] * x + GAL[0][1] * y + GAL[0][2] * z,
                            GAL[1][0] * x + GAL[1][1] * y + GAL[1][2] * z,
                            GAL[2][0] * x + GAL[2][1] * y + GAL[2][2] * z);
          if (mw) {
            r += 22 * mw[0] + 44 * mw[1];
            g += 25 * mw[0] + 38 * mw[1];
            b += 35 * mw[0] + 31 * mw[1];
          }
          /* The zodiacal light: sunlight off interplanetary dust, a cone along the ecliptic. */
          var beta = Math.abs(Math.asin(Math.max(-1, Math.min(1, -y * v.se + z * v.ce)))) / RAD;
          var zod = Math.exp(-beta / (4 + 0.12 * th)) * Math.pow(9 / Math.max(th, 5), 1.3) * 0.11;
          r += 255 * zod; g += 236 * zod; b += 212 * zod;
          var o = (row * lw + col) * 4, dither = (rand() - 0.5) * 1.4;
          d[o] = r + dither; d[o + 1] = g + dither; d[o + 2] = b + dither; d[o + 3] = 255;
        }
      }
      lctx.putImageData(img, 0, 0);
      return low;
    }

    /* The stars, from the catalogue, at their magnitude and colour. The sunset's glare and
       the air at the limb wash out the faint ones. */
    function drawStars(v) {
      var A = v.A, U = v.U, X = v.X, Sd = v.S, f = v.f, gx = v.gx, gy = v.gy;
      var corner = Math.max(Math.hypot(gx, gy), Math.hypot(v.SW - gx, gy), Math.hypot(gx, v.SH - gy),
                            Math.hypot(v.SW - gx, v.SH - gy));
      var zmin = Math.cos(Math.atan(corner / f));
      /* A small screen packs more sky into each pixel: draw fewer faint stars there, so they
         stay as sparse as on a desktop (about three times as many stars per magnitude). */
      var vmax = Math.min(6.5, 6.5 + 4.2 * Math.log(f / 740) / Math.LN10);
      for (var i = 0; i < stars.n; i++) {
        if (stars.mag[i] > vmax) continue;
        var j = i * 3, sx = stars.xyz[j], sy = stars.xyz[j + 1], sz = stars.xyz[j + 2];
        var zc = sx * A[0] + sy * A[1] + sz * A[2];
        if (zc < zmin) continue;
        var px = gx + f * (sx * X[0] + sy * X[1] + sz * X[2]) / zc;
        var py = gy - f * (sx * U[0] + sy * U[1] + sz * U[2]) / zc;
        if (px < -4 || py < -4 || px > v.SW + 4 || py > v.SH + 4) continue;
        var rg = Math.hypot(px - gx, py - gy) / R;
        if (rg < 1) continue;
        var m = stars.mag[i];
        var ths = Math.acos(Math.max(-1, Math.min(1, sx * Sd[0] + sy * Sd[1] + sz * Sd[2]))) / RAD;
        var fade = smoothstep(1, 1.07, rg) * (0.3 + 0.7 * smoothstep(3, 16, ths));
        var a = clamp01(0.3 + (vmax - m) * 0.17) * fade;
        if (a < 0.03) continue;
        var rad = 0.55 + Math.max(0, 5.5 - m) * 0.2, col = starColour(stars.bv[i]);
        var cs = col[0] + ',' + col[1] + ',' + col[2];
        if (m < 2.6) {
          var gr = rad * (3.4 + (2.6 - m) * 1.3);
          var gl = sctx.createRadialGradient(px, py, 0, px, py, gr);
          gl.addColorStop(0, 'rgba(' + cs + ',' + (0.3 * fade) + ')');
          gl.addColorStop(0.35, 'rgba(' + cs + ',' + (0.08 * fade) + ')');
          gl.addColorStop(1, 'rgba(' + cs + ',0)');
          sctx.fillStyle = gl;
          sctx.beginPath(); sctx.arc(px, py, gr, 0, TAU); sctx.fill();
        }
        sctx.fillStyle = 'rgba(' + cs + ',' + a + ')';
        sctx.beginPath(); sctx.arc(px, py, rad, 0, TAU); sctx.fill();
      }
    }

    /* The brush stroke, bristle by bristle: wet ink for what is verified, drying out over
       what is only estimated. `p` is how far the stroke has travelled. */
    var bristles = null;

    function brushSetup() {
      var rand2 = mulberry(1609), width = 38 * S, count = Math.round(width * 2.6);
      bristles = [];
      for (var b = 0; b < count; b++) {
        var u = b / (count - 1) - 0.5, edge = Math.abs(u) * 2;
        bristles.push({
          offset: u * width + (rand2() - 0.5) * 1.1,
          edge: edge,
          alpha: 0.5 + rand2() * 0.42,
          width: (0.55 + rand2() * 0.75) * S,
          head: edge * edge * 0.05 + rand2() * 0.012,
          tail: edge * edge * edge * 0.2 + rand2() * 0.1,
          gaps: pressure(1400, rand2, 7 + Math.floor(rand2() * 14)),
          wander: pressure(1400, rand2, 90)
        });
      }
    }

    function drawBrush(p) {
      var c = octx;
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
      c.clearRect(0, 0, W, H);
      c.lineCap = 'round';
      var arc = share * TAU, dryFrom = verifiedShare / share;
      var steps = Math.min(1399, Math.ceil(arc * ringR / 0.9));
      /* By night the stroke is the sunset: gold where it is wet, through orange to rose. */
      var light = null;
      if (T.brush) {
        var bc = T.brush;
        if (c.createConicGradient) {
          light = c.createConicGradient(TOP, cx, cy);
          light.addColorStop(0, 'rgb(' + bc[0] + ')');
          light.addColorStop(share * dryFrom, 'rgb(' + bc[1] + ')');
          light.addColorStop(share, 'rgb(' + bc[2] + ')');
          light.addColorStop(1, 'rgb(' + bc[2] + ')');
        } else {
          light = 'rgb(' + bc[1] + ')';
        }
      }
      bristles.forEach(function (b) {
        c.beginPath();
        var pen = false, last = Math.floor(steps * p);
        for (var i = 0; i <= last; i++) {
          var t = i / steps;
          if (t < b.head || t > 1 - b.tail) { pen = false; continue; }
          var dry = t < dryFrom ? 0.05 : Math.min(0.9, 0.05 + (t - dryFrom) / (1 - dryFrom) * 0.86);
          if (b.gaps[i] < dry * (0.55 + 0.6 * b.edge)) { pen = false; continue; }
          var a = TOP + t * arc;
          var r = ringR + b.offset + (b.wander[i] - 0.5) * 2.4 * S;
          var sx = cx + Math.cos(a) * r, sy = cy + Math.sin(a) * r;
          c[pen ? 'lineTo' : 'moveTo'](sx, sy);
          pen = true;
        }
        if (light) {
          c.globalAlpha = b.alpha;
          c.strokeStyle = light;
        } else {
          c.strokeStyle = 'rgba(' + INK + ',' + b.alpha + ')';
        }
        c.lineWidth = b.width;
        c.stroke();
      });
      c.globalAlpha = 1;

      /* What the brush throws off as it leaves the paper. */
      var rand2 = mulberry(58), reach = (1 - verifiedShare / share) * arc;
      c.fillStyle = rgba(T.spatter);
      for (var i = 0; i < 46; i++) {
        var along = Math.pow(rand2(), 1.6), side = rand2() < 0.5 ? -1 : 1;
        var when = 1 - along * reach / arc, size = (0.35 + Math.pow(rand2(), 3) * 2.1) * S;
        var off = side * (21 + rand2() * rand2() * 58) * S;
        if (when > p) continue;
        var ang = TOP + when * arc + 0.015 * rand2(), rad = ringR + off;
        c.beginPath();
        c.arc(cx + Math.cos(ang) * rad, cy + Math.sin(ang) * rad, size, 0, TAU);
        c.fill();
      }
    }

    /* Hovering a country marks its slice of the stroke. */
    var slices = [], brushCache = null;

    function buildSlices() {
      var sum = 0;
      slices = earth.atlases.map(function (a) {
        var from = sum;
        sum += a.best / 1000 / earth.world.gw;
        return { atlas: a, from: from, to: sum };
      });
    }

    function cacheBrush() {
      brushCache = document.createElement('canvas');
      brushCache.width = over.width; brushCache.height = over.height;
      brushCache.getContext('2d').drawImage(over, 0, 0);
    }

    function drawOver() {
      var c = octx;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, over.width, over.height);
      if (brushCache) c.drawImage(brushCache, 0, 0);
      if (!hovered || !hovered.atlas) return;
      var slice = slices.filter(function (s) { return s.atlas === hovered.atlas; })[0];
      if (!slice) return;
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
      var a0 = TOP + slice.from * TAU, a1 = TOP + slice.to * TAU;
      if (a1 - a0 < 0.012) a1 = a0 + 0.012;    // a very small atlas still shows
      c.beginPath();
      c.arc(cx, cy, ringR + 19 * S, a0, a1);
      c.strokeStyle = 'rgba(' + T.red + ',.95)';
      c.lineWidth = 3.4 * S;
      c.lineCap = 'butt';
      c.stroke();
    }

    function placeLabels() {
      var narrow = window.innerWidth <= NARROW_W || window.innerHeight <= 620;
      el('readout-share').textContent = (share * 100).toFixed(1) + '%';
      var best = el('readout-best'), readoutY = 0;
      best.textContent = '';
      best.appendChild(document.createTextNode((earth.best_mwp / 1000).toLocaleString('en-US',
        { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' GW best estimate'));
      best.appendChild(document.createElement('br'));
      best.appendChild(document.createTextNode('in ' + earth.atlases.length + ' countries'));
      if (!narrow) {
        var a = TOP + share * TAU + 0.05;
        readout.style.left = (cx + Math.cos(a) * (ringR + 34 * S)) + 'px';
        readoutY = cy + Math.sin(a) * (ringR + 34 * S);
        var b = TOP - 0.05;
        worldLabel.style.left = (cx + Math.cos(b) * (ringR + 18 * S)) + 'px';
        worldLabel.style.top = (cy + Math.sin(b) * (ringR + 18 * S) - 10) + 'px';
      } else {
        readout.style.left = readout.style.top = '';
      }
      worldLabel.innerHTML = '';
      worldLabel.appendChild(document.createTextNode('about ' + earth.world.gw.toLocaleString('en-US') + ' GW worldwide'));
      worldLabel.appendChild(document.createElement('br'));
      var src = document.createElement('a');
      src.href = earth.world.url;
      src.textContent = earth.world.short + ', ' + earth.world.as_of_label;
      worldLabel.appendChild(src);
      worldLabel.hidden = narrow;
      readout.hidden = false;
      /* The share centred on the stroke's end: the lines beside it are taller than it is. */
      if (!narrow) readout.style.top = (readoutY - readout.offsetHeight / 2) + 'px';
    }

    function resize() {
      var box = stage.getBoundingClientRect();
      W = box.width; H = box.height;
      DPR = Math.min(window.devicePixelRatio || 1, quality > 1 ? 2 : 1);
      [under, canvas, over].forEach(function (c) {
        c.width = Math.round(W * DPR);
        c.height = Math.round(H * DPR);
      });
      var narrow = window.innerWidth <= NARROW_W || window.innerHeight <= 620;
      /* Stacked, the percentage and its two lines of figures sit above the ring: landing.css
         gives the stage 40px for those lines, and the globe moves down by as much. */
      var room = narrow ? Math.min(W / 2 - 10, H / 2 - 44) : Math.min(W / 2 - 40, H / 2 - 34);
      ringR = room - (narrow ? 26 : 30);
      R = ringR / (narrow ? 1.1 : 1.095);
      S = R / 300;
      cx = W / 2;
      cy = H / 2 + (narrow ? 34 : 12);
      projection.translate([cx, cy]).scale(R);
      rasterSetup();
      brushSetup();
      buildSlices();
      drawUnder();
      placeLabels();
      scheduleSky();
      if (intro >= 1) {
        drawBrush(1);
        cacheBrush();
        drawOver();
      }
      dirty = true;
    }

    /* ---------------------------------------------------------------- interaction */
    var dirty = true, last = 0, lastAuto = 0;
    var hold = 0, overGlobe = false, dragging = null, velocity = [0, 0], fly = null;
    var slow = 0, frames = 0;

    function featureAt(lon, lat) {
      for (var i = 0; i < features.length; i++) {
        var f = features[i], b = f.bounds;
        if (lat < b[0][1] - 0.02 || lat > b[1][1] + 0.02) continue;
        var w = b[0][0], e = b[1][0];
        if (w <= e ? (lon < w - 0.02 || lon > e + 0.02) : (lon < w - 0.02 && lon > e + 0.02)) continue;
        if (d3.geoContains(f.feature, [lon, lat])) return f.regions ? regionAt(f, lon, lat) : f;
      }
      return null;
    }

    function inPolygon(rings, lon, lat) {
      var inside = false;
      rings.forEach(function (ring) {
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          var a = ring[i], b = ring[j];
          if ((a[1] > lat) !== (b[1] > lat) && lon < (b[0] - a[0]) * (lat - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
        }
      });
      return inside;
    }

    /* The state under a point of its country, or on a coastal sliver the nearest one. */
    function regionAt(country, lon, lat) {
      var nearest = country.regions[0], best = Infinity;
      for (var i = 0; i < country.regions.length; i++) {
        var region = country.regions[i];
        for (var p = 0; p < region.rings.length; p++) {
          if (inPolygon(region.rings[p], lon, lat)) return region;
          var ring = region.rings[p][0];
          for (var v = 0; v < ring.length; v++) {
            var dx = ring[v][0] - lon, dy = ring[v][1] - lat, d = dx * dx + dy * dy;
            if (d < best) { best = d; nearest = region; }
          }
        }
      }
      return nearest;
    }

    function pick(event) {
      var box = canvas.getBoundingClientRect();
      var x = event.clientX - box.left, y = event.clientY - box.top;
      if ((x - cx) * (x - cx) + (y - cy) * (y - cy) > R * R) return null;
      var ll = projection.invert([x, y]);
      return ll ? featureAt(ll[0], ll[1]) : null;
    }

    /* MW below a gigawatt, GW from there up: 7.4 MW, 530 MW, 1.8 GW, 103 GW. */
    function power(mwp) {
      if (mwp >= 1000) return (mwp / 1000).toFixed(mwp >= 100000 ? 0 : 1) + ' GW';
      return mwp.toFixed(mwp >= 10 ? 0 : 1) + ' MW';
    }

    /* The atlas's size chart in four bars (owner, 2026-11-11): earth.json's `size_labels`
       and the atlas's `facts.sizes` in MWp, each bar's length against the longest, its figure
       beside it, the bar below 400 m² in vermilion. Where a page has no rooftop detector below
       the floor that bar holds only part of what is there, so it fades on past its end and its
       figure reads "at least"; one that rounds to nothing reads "not measured". */
    function fillSizes(a) {
      var box = el('card-sizes');
      box.textContent = '';
      box.hidden = !a;
      if (!a) return;
      var t = a.facts, top = Math.max.apply(null, t.sizes) || 1;
      var span = function (cls, text) {
        var s = document.createElement('span');
        s.className = cls;
        if (text) s.textContent = text;
        return s;
      };
      box.appendChild(span('card__sizes-head', 'By installation size'));
      t.sizes.forEach(function (mwp, i) {
        var small = i === 0 ? ' is-small' : '';
        var floor = !!small && !t.rooftop_measured, none = floor && mwp < 0.05;
        var track = span('card__size-track'), bar = span('card__size-bar' + small);
        bar.style.width = (mwp > 0 ? Math.max(1.5, 88 * mwp / top) : 0) + '%';
        track.appendChild(bar);
        if (floor && !none) track.appendChild(span('card__size-fade'));
        box.appendChild(span('card__size-label' + small, earth.size_labels[i]));
        box.appendChild(track);
        box.appendChild(span('card__size-value' + small + (none ? ' not-measured' : ''),
          none ? 'not measured' : (floor ? 'at least ' : '') + (mwp < 0.05 ? '0 MW' : power(mwp))));
      });
    }

    /* One sentence, behind the warning sign (owner, 2026-11-13), only where small rooftops are
       uncalibrated: a missing farm detector alone (Pakistan, Germany) gets no warning (owner).
       Yemen's farm ground is calibrated, so its sentence names rooftops. */
    function unmeasuredNote(t) {
      if (t.rooftop_measured) return '';
      return t.farm_ground_measured ? 'No small-rooftop detector has been calibrated here yet.'
                                    : 'No small-array detector has been calibrated here yet.';
    }

    function linkFor(f) {
      if (f.atlas) return f.atlas.href;
      var q = '?country=' + encodeURIComponent(f.name) +
              (f.iso ? '&iso3=' + f.iso : '') + '&bbox=' + f.box.join(',') +
              (f.division ? '&division=' + encodeURIComponent(f.division) : '');
      return NEW_ATLAS + q;
    }

    function fillCard(f) {
      el('card-name').textContent = f.name;
      el('card-head').dataset.tier = f.atlas ? f.atlas.tier : '';
      if (f.atlas) {
        el('card-tier').textContent = f.atlas.tier + ' atlas';
        el('card-best').textContent = power(f.atlas.best) + ' best estimate';
        fillSizes(f.atlas);
        el('card-note').textContent = unmeasuredNote(f.atlas.facts);
        el('card-go').textContent = 'Open the atlas →';
      } else {
        el('card-tier').textContent = f.kind || '';
        el('card-best').textContent = 'No atlas yet.';
        fillSizes(null);
        el('card-note').textContent = '';
        el('card-go').textContent = 'Build it on your PC →';
      }
      card.href = linkFor(f);
    }

    function placeCard(x, y) {
      var bw = card.offsetWidth, bh = card.offsetHeight;
      var left = x + 18, top = y - bh - 12;
      if (left + bw > W - 8) left = x - bw - 18;
      if (top < 8) top = y + 18;
      left = Math.max(8, Math.min(left, W - bw - 8));   // a tall card must stay on the page
      top = Math.max(8, Math.min(top, H - bh - 8));
      card.style.left = left + 'px';
      card.style.top = top + 'px';
    }

    function setHovered(f) {
      if (f === hovered) return;
      hovered = f;
      dirty = true;
      canvas.classList.toggle('is-over', !!f);
      if (intro >= 1) drawOver();
    }

    var pinTimer = 0;

    function hideCard() {
      clearTimeout(pinTimer);
      card.hidden = true;
      card.classList.remove('is-pinned');
    }

    /* A tap beside the card, off the globe, puts it away: it can cover most of a phone. */
    document.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'touch' || card.hidden) return;
      if (canvas.contains(e.target) || card.contains(e.target)) return;
      setHovered(null);
      hideCard();
    });

    canvas.addEventListener('pointermove', function (e) {
      if (dragging) {
        var dx = e.clientX - dragging.x, dy = e.clientY - dragging.y;
        dragging.x = e.clientX; dragging.y = e.clientY;
        dragging.moved += Math.abs(dx) + Math.abs(dy);
        if (dragging.moved > 5) { hideCard(); canvas.classList.add('is-drag'); }
        var k = 180 / (Math.PI * R);
        rot[0] += dx * k;
        rot[1] = Math.max(-75, Math.min(75, rot[1] - dy * k));
        velocity = [dx * k, -dy * k];
        dirty = true;
        return;
      }
      if (e.pointerType === 'touch') return;
      overGlobe = true;
      var f = pick(e);
      setHovered(f);
      if (f) {
        fillCard(f);
        card.hidden = false;
        var box = stage.getBoundingClientRect();
        placeCard(e.clientX - box.left, e.clientY - box.top);
      } else {
        hideCard();
      }
    });

    canvas.addEventListener('pointerleave', function (e) {
      if (dragging || e.pointerType === 'touch') return;   // a lifted finger "leaves" too
      overGlobe = false;
      setHovered(null);
      hideCard();
    });

    canvas.addEventListener('pointerdown', function (e) {
      canvas.setPointerCapture(e.pointerId);
      dragging = { x: e.clientX, y: e.clientY, moved: 0 };
      velocity = [0, 0];
      fly = null;
    });

    function endDrag(e) {
      if (!dragging) return;
      var tap = dragging.moved <= 5;
      dragging = null;
      canvas.classList.remove('is-drag');
      hold = performance.now() + 1400;
      if (!tap || e.type === 'pointercancel') {
        if (e.pointerType !== 'touch') setHovered(pick(e));   // the pointer has moved on
        return;
      }
      var f = pick(e);
      if (!f) {
        if (e.pointerType === 'touch') { setHovered(null); hideCard(); }
        return;
      }
      if (e.pointerType === 'touch') {
        /* No hover on touch: the first tap shows what it would open. The card takes taps
           only once this tap's own click has passed, or that click would land on the card
           appearing under the finger and open the atlas straight away. */
        setHovered(f);
        fillCard(f);
        card.hidden = false;
        card.classList.remove('is-pinned');
        clearTimeout(pinTimer);
        pinTimer = setTimeout(function () { card.classList.add('is-pinned'); }, 400);
        var box = stage.getBoundingClientRect();
        placeCard(e.clientX - box.left, e.clientY - box.top);
        return;
      }
      window.location.href = new URL(linkFor(f), document.baseURI).href;
    }
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);

    /* The country links turn the globe to their country. */
    function flyTo(f) {
      var c = d3.geoCentroid(f.feature);
      var target = [-c[0], Math.max(-55, Math.min(55, -c[1])), 0];
      var delta = ((target[0] - rot[0]) % 360 + 540) % 360 - 180;
      if (REDUCED) {
        rot = [rot[0] + delta, target[1], 0];
        dirty = true;
        return;
      }
      fly = { t0: performance.now(), dur: 700, from: rot.slice(), dl: delta, to: target };
    }
    document.querySelectorAll('.atlas-links a[data-iso]').forEach(function (a) {
      var f = featureByName[a.textContent.trim()];
      if (!f) return;
      function on() { setHovered(f); flyTo(f); overGlobe = true; }
      function off() { setHovered(null); overGlobe = false; hold = performance.now() + 900; }
      a.addEventListener('pointerenter', on);
      a.addEventListener('focus', on);
      a.addEventListener('pointerleave', off);
      a.addEventListener('blur', off);
    });

    /* ----------------------------------------------------------------- the loop */
    var introStart = 0, introDone = REDUCED;

    function frame(now) {
      requestAnimationFrame(frame);
      var dt = last ? Math.min(100, now - last) : 16;
      last = now;

      if (!introDone) {
        if (!introStart) introStart = now;
        var t = Math.min(1, (now - introStart) / 2300);
        intro = 1 - Math.pow(1 - t, 2.2);
        drawBrush(intro);
        dirty = true;
        if (t >= 1) {
          intro = 1;
          introDone = true;
          cacheBrush();
          readout.classList.add('is-on');
          worldLabel.classList.add('is-on');
          hold = now + 300;
        }
      }

      var moving = false;
      if (fly) {
        var ft = Math.min(1, (now - fly.t0) / fly.dur);
        var e = ft * ft * (3 - 2 * ft);
        rot[0] = fly.from[0] + fly.dl * e;
        rot[1] = fly.from[1] + (fly.to[1] - fly.from[1]) * e;
        if (ft >= 1) fly = null;
        dirty = true;
        moving = true;
      } else if (!dragging && (Math.abs(velocity[0]) > 0.01 || Math.abs(velocity[1]) > 0.01)) {
        rot[0] += velocity[0];
        rot[1] = Math.max(-75, Math.min(75, rot[1] + velocity[1]));
        var decay = Math.pow(0.93, dt / 16);
        velocity[0] *= decay; velocity[1] *= decay;
        dirty = true;
        moving = true;
      } else if (!REDUCED && !dragging && !overGlobe && now > hold) {
        if (now - lastAuto >= 1000 / AUTO_FPS) {
          rot[0] += SPIN_DEG_S * (lastAuto ? Math.min(120, now - lastAuto) : 40) / 1000;
          lastAuto = now;
          dirty = true;
        }
      }

      if (!dirty) return;
      dirty = false;
      var t0 = performance.now();
      draw();
      var spent = performance.now() - t0;
      if (introDone && !document.documentElement.dataset.earthReady) {
        document.documentElement.dataset.earthReady = '1';
      }

      /* On a slow machine give up resolution first, then the second pencil line. */
      if (introDone && !moving) {
        frames++;
        if (spent > 44) slow++;
        if (frames >= 40) {
          if (slow > 26 && quality > 0) {
            quality--;
            resize();
          }
          frames = slow = 0;
        }
      }
    }

    /* The switch in the header, or the system, changed the theme: redraw everything. */
    new MutationObserver(function () {
      var was = T;
      setTheme();
      if (T === was) return;
      if (!T.dark && sky) sky.width = sky.height = 0;
      skyDone = false;
      if (W) resize();
    }).observe(root, { attributes: true, attributeFilter: ['data-theme'] });

    (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(function () {
      resize();
      window.addEventListener('resize', resize);
      if (REDUCED) {
        drawBrush(1);
        cacheBrush();
        readout.classList.add('is-on');
        worldLabel.classList.add('is-on');
      }
      requestAnimationFrame(frame);
    });
  }

  /* stars.json: four integers a star, RA and Dec in 0.02 degree, V and B-V in tenths. */
  function decodeStars(doc) {
    var s = doc.stars, n = s.length / 4;
    var out = { n: n, xyz: new Float32Array(n * 3), mag: new Float32Array(n), bv: new Float32Array(n) };
    for (var i = 0; i < n; i++) {
      unit(s[i * 4] * 0.02, s[i * 4 + 1] * 0.02, out.xyz, i * 3);
      out.mag[i] = s[i * 4 + 2] / 10;
      out.bv[i] = s[i * 4 + 3] / 10;
    }
    return out;
  }

  function json(name) {
    return fetch(BASE + name).then(function (r) {
      if (!r.ok) throw new Error(name + ': ' + r.status);
      return r.json();
    });
  }

  function boot() {
    Promise.all([json('world.json'), json('earth.json'), json('regions.json').catch(function () { return null; })])
      .then(function (d) { start(d[0], d[1], d[2]); })
      .catch(function (err) {
        /* The country links and figures are plain HTML and still work. */
        if (window.console) console.error('Electrify Earth:', err);
      });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
