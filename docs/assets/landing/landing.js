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

  function el(id) { return document.getElementById(id); }

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

    document.body.style.backgroundImage = 'url(' + paperTile().toDataURL() + ')';

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

    /* From a blush on the white land to full vermilion, over a log scale of MW in one cell.
       Opaque: the land under a cell with solar is white whatever the wash beneath it. */
    var LOG_LOW = -2, LOG_HIGH = Math.log(RED_MW) / Math.LN10;
    var ramp = (function () {
      var stops = [[0, 252, 240, 233, 1], [0.25, 249, 222, 209, 1], [0.5, 241, 176, 152, 1],
                   [0.726, 224, 112, 80, 1], [0.85, 198, 68, 38, 1], [1, 163, 44, 16, 1]];
      var out = new Uint32Array(256), s = 0;
      for (var i = 0; i < 256; i++) {
        var u = i / 255;
        while (s < stops.length - 2 && u > stops[s + 1][0]) s++;
        var a = stops[s], b = stops[s + 1], t = (u - a[0]) / (b[0] - a[0]);
        var mix = function (k) { return a[k] + (b[k] - a[k]) * t; };
        out[i] = ((mix(4) * 255) << 24) | (mix(3) << 16) | (mix(2) << 8) | mix(1);
      }
      return out;
    })();

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
      var red = new Path2D();
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
        }
      }

      for (i = 0; i < rCount; i++) {
        o = rTouched[i];
        if (rMW[o] > 0) {
          var u = (Math.log(rMW[o]) / Math.LN10 - LOG_LOW) / (LOG_HIGH - LOG_LOW);
          rPixels[o] = ramp[u <= 0 ? 0 : u >= 1 ? 255 : Math.round(u * 255)];
        } else {
          rPixels[o] = ((Math.min(1, rTone[o] * 1.3) * TONE_ALPHA * 255) << 24) | (248 << 16) | (253 << 8) | 255;
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

      ctx.fillStyle = 'rgba(' + RED + ',.92)';
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
      ctx.fillStyle = 'rgba(' + INK + ',.05)';
      ctx.fill();
      strokeSet(lineSets.hatch, [0.35, 0.55, 0.8], 0.26, INK, 0.16);

      strokeSet(lineSets.grat, [0.5], 0.13, INK, 0.3);
      strokeSet(lineSets.pencilBorder, [0.45, 0.7], 0.3, INK, 0.1);
      strokeSet(lineSets.regionBorder, [0.35, 0.55], 0.28, INK, 0.1);
      if (quality > 0) strokeSet(lineSets.pencilGhost, [0.4, 0.6], 0.2, INK, 0.3);
      strokeSet(lineSets.pencilCoast, [0.5, 0.75, 1.05], 0.62, INK, 0.08);

      /* A country with an atlas: only a trace of wash, for whatever its atlas did not image.
         What it did image is laid over this in white. */
      ctx.beginPath();
      path(inked);
      if (inkedRegions) path(inkedRegions);
      ctx.fillStyle = 'rgba(' + INK + ',' + (0.05 * ink) + ')';
      ctx.fill();

      if (hovered && !hovered.atlas) {
        ctx.beginPath();
        path(hovered.feature);
        ctx.fillStyle = 'rgba(' + RED + ',.14)';
        ctx.fill();
      }

      drawCells(ink);

      if (quality > 0) strokeSet(lineSets.inkGhost, [0.4, 0.7], 0.35 * ink, INK, 0.2);
      strokeSet(lineSets.ink, [0.55, 0.8, 1.1, 1.5, 2], 0.95 * ink, INK, 0);

      if (hovered) {
        ctx.beginPath();
        path(hovered.feature);
        ctx.strokeStyle = 'rgba(' + RED + ',.95)';
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

    function drawUnder() {
      var c = uctx;
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
      c.clearRect(0, 0, W, H);

      /* Opaque, so that the sheet's fibres do not show through land turning over them. */
      c.fillStyle = '#f8f4ec';
      c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();

      /* The sphere: a little brighter than the sheet, darkening at the limb. */
      var g = c.createRadialGradient(cx - R * 0.28, cy - R * 0.34, R * 0.1, cx, cy, R);
      g.addColorStop(0, 'rgba(255,253,248,.22)');
      g.addColorStop(0.75, 'rgba(255,253,248,.05)');
      g.addColorStop(0.93, 'rgba(60,52,42,.03)');
      g.addColorStop(1, 'rgba(60,52,42,.11)');
      c.fillStyle = g;
      c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();

      /* Sketched shadow: hatching in a crescent away from the light. */
      var rand2 = mulberry(31), lightX = cx - R * 0.07, lightY = cy - R * 0.08, lightR = R * 0.955;
      var dirX = Math.cos(1.12), dirY = Math.sin(1.12), nx = -dirY, ny = dirX;
      c.lineCap = 'round';
      for (var d = -R; d < R; d += 3.4 * S) {
        var run = null;
        var flush = function () {
          if (run && run.length > 1) {
            c.beginPath();
            run.forEach(function (p, i) { c[i ? 'lineTo' : 'moveTo'](p[0], p[1]); });
            c.strokeStyle = 'rgba(' + INK + ',' + (0.1 + rand2() * 0.16) + ')';
            c.lineWidth = (0.35 + rand2() * 0.5) * S;
            c.stroke();
          }
          run = null;
        };
        for (var t = -R; t < R; t += 3) {
          var px = cx + nx * d + dirX * t + (rand2() - 0.5) * 0.7;
          var py = cy + ny * d + dirY * t + (rand2() - 0.5) * 0.7;
          var inside = (px - cx) * (px - cx) + (py - cy) * (py - cy) < (R - 1.2) * (R - 1.2);
          var lit = (px - lightX) * (px - lightX) + (py - lightY) * (py - lightY) < lightR * lightR;
          if (inside && !lit) (run = run || []).push([px, py]);
          else flush();
        }
        flush();
      }

      /* The sphere's own outline, thin on the lit side. */
      brushDisc(c, R, function (a, p) {
        var side = 0.5 + 0.5 * Math.cos(a - 0.85);
        return (0.5 + 2.1 * side * side + p * 0.7) * S;
      }, 'rgba(' + INK + ',.88)');

      /* The pencil ring: the whole world's PV, still to be drawn over. */
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
        c.strokeStyle = 'rgba(' + INK + ',' + (pass ? 0.2 : 0.4) + ')';
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
        c.strokeStyle = 'rgba(' + INK + ',.55)';
        c.lineWidth = 0.9 * S;
        c.stroke();
        c.fillStyle = 'rgba(' + INK + ',.62)';
        c.fillText(gw.toLocaleString('en-US') + (gw === 500 ? ' GW' : ''), cx + ca * (ringR + 21 * S), cy + sa * (ringR + 21 * S));
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
        c.strokeStyle = 'rgba(' + INK + ',' + b.alpha + ')';
        c.lineWidth = b.width;
        c.stroke();
      });

      /* What the brush throws off as it leaves the paper. */
      var rand2 = mulberry(58), reach = (1 - verifiedShare / share) * arc;
      c.fillStyle = 'rgba(' + INK + ',.82)';
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
      c.strokeStyle = 'rgba(' + RED + ',.95)';
      c.lineWidth = 3.4 * S;
      c.lineCap = 'butt';
      c.stroke();
    }

    function placeLabels() {
      var narrow = window.innerWidth <= NARROW_W || window.innerHeight <= 620;
      el('readout-share').textContent = (share * 100).toFixed(1) + '%';
      if (!narrow) {
        var a = TOP + share * TAU + 0.05;
        readout.style.left = (cx + Math.cos(a) * (ringR + 34 * S)) + 'px';
        readout.style.top = (cy + Math.sin(a) * (ringR + 34 * S) - 26) + 'px';
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
      var room = narrow ? Math.min(W / 2 - 10, H / 2 - 24) : Math.min(W / 2 - 40, H / 2 - 34);
      ringR = room - (narrow ? 26 : 30);
      R = ringR / (narrow ? 1.1 : 1.095);
      S = R / 300;
      cx = W / 2;
      cy = H / 2 + (narrow ? 14 : 12);   // stacked, the percentage sits above the ring
      projection.translate([cx, cy]).scale(R);
      rasterSetup();
      brushSetup();
      buildSlices();
      drawUnder();
      placeLabels();
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

    function energy(gwh) {
      if (gwh < 1000) return Math.round(gwh) + ' GWh';
      return (gwh / 1000).toFixed(gwh >= 100000 ? 0 : 1) + ' TWh';
    }

    function imageryMonth(iso) {
      var parts = iso.split('-');
      return ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][+parts[1] - 1] + ' ' + parts[0];
    }

    /* The essentials only: the atlas itself has the rest. A figure a page lacks is left out,
       and farm ground it did not measure says so: never 0. */
    function atlasRows(a) {
      var t = a.facts, rows = [];
      if (t.gwh != null) rows.push(['Generates', 'about ' + energy(t.gwh) + ' a year']);
      if (t.imagery) rows.push(['Imagery', 'around ' + imageryMonth(t.imagery)]);
      rows.push(['OpenStreetMap under 400 m²', t.osm_lt400.toLocaleString('en-US') + ' mapped']);
      rows.push(['OpenStreetMap 400 m² and up', t.osm_ge400.toLocaleString('en-US') + ' mapped']);
      rows.push(t.farm_ground != null
        ? ['Farm ground under 400 m²', power(t.farm_ground)]
        : ['Farm ground under 400 m²', 'not measured', 'not-measured']);
      return rows;
    }

    function fillFacts(rows) {
      var list = el('card-facts');
      list.textContent = '';
      list.hidden = !rows;
      (rows || []).forEach(function (row) {
        var dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = row[0];
        dd.textContent = row[1];
        if (row[2]) dd.className = row[2];
        list.appendChild(dt);
        list.appendChild(dd);
      });
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
      if (f.atlas) {
        el('card-tier').textContent = f.atlas.tier + ' atlas';
        el('card-best').textContent = power(f.atlas.best) + ' best estimate';
        el('card-verified').textContent = power(f.atlas.verified) + ' verified';
        fillFacts(atlasRows(f.atlas));
        el('card-go').textContent = 'Open the atlas →';
      } else {
        el('card-tier').textContent = f.kind || '';
        el('card-best').textContent = 'No atlas yet.';
        el('card-verified').textContent = '';
        fillFacts(null);
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
