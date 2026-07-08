// GameVault RPG Maker — case-insensitive asset loader (NW.js inject_js_start)
//
// Linux filesystems are case-sensitive; RPG Maker MV/MZ data frequently
// references assets with different capitalization than the file on disk
// (Windows ignores case), producing "Failed to load: img/....png" and a dead
// game. This shim indexes the game's content tree once at boot, then rewrites
// any asset request whose exact-case path is missing to the real file. It only
// intervenes when the exact path does NOT exist, so correct games are untouched.
//
// Covers every load path MV/MZ uses: images (Image.src), audio/video
// (HTMLMediaElement.src), and data + decrypted assets (XMLHttpRequest). Runs in
// the page at document-start with Node integration, so require('fs') is available.
// Any failure is swallowed — the game boots regardless.
(function () {
  var DBG = null;
  function dbg(msg) {
    try { console.log(msg); } catch (_) {}
    try { if (DBG) DBG.appendFileSync(DBG.__log, msg + '\n'); } catch (_) {}
  }
  try { console.log('[casefix] script executing in page'); } catch (_) {}
  try {
    // inject_js_start may run in a context without a bare `require`; try the
    // usual NW.js escape hatches before giving up.
    var req = (typeof require === 'function' && require) ||
              (typeof window !== 'undefined' && window.require) ||
              (typeof global !== 'undefined' && global.require) ||
              (typeof nw !== 'undefined' && nw.require) || null;
    try { console.log('[casefix] require = ' + (req ? 'FOUND' : 'NULL')); } catch (_) {}
    if (!req) { return; }
    var fs = req('fs');
    var path = req('path');
    // NW.js serves the app from a chrome-extension:// origin, so
    // window.location.pathname is the VIRTUAL package path ("/www/index.html"),
    // not the real filesystem path. Derive the real content dir from
    // process.mainModule.filename (the entry html) — the same path MV itself
    // uses to locate its save/ folder. Fall back to location only if unavailable.
    var baseDir = null;
    try { baseDir = path.dirname(process.mainModule.filename); } catch (e) {}
    if (!baseDir || !fs.existsSync(baseDir)) {
      baseDir = path.dirname(decodeURIComponent(window.location.pathname));
      if (/^\/[A-Za-z]:\//.test(baseDir)) baseDir = baseDir.slice(1);
    }

    // wire debug sink (best-effort) — casefix.log next to the game content
    DBG = fs; DBG.__log = path.join(baseDir, 'casefix.log');
    try { fs.writeFileSync(DBG.__log, ''); } catch (_) {}
    dbg('[casefix] loaded; baseDir=' + baseDir + '; require=' + (typeof require === 'function' ? 'bare' : 'fallback'));

    // lower(relPath) -> real relPath (forward-slash), for files AND dirs.
    var index = Object.create(null);
    var count = 0;
    function walk(dir, rel) {
      var ents;
      try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
      for (var i = 0; i < ents.length; i++) {
        var name = ents[i].name;
        var childRel = rel ? rel + '/' + name : name;
        index[childRel.toLowerCase()] = childRel;
        count++;
        if (ents[i].isDirectory()) walk(path.join(dir, name), childRel);
      }
    }
    walk(baseDir, '');
    dbg('[casefix] baseDir=' + baseDir + ' indexed ' + count + ' entries');

    // Virtual package root of the entry html (e.g. "/www") — absolute
    // chrome-extension:// URLs are rooted here and map onto baseDir.
    var virtualBase = path.dirname(decodeURIComponent(window.location.pathname));

    // Given a request URL/path, return {abs, rel, absolute, suffix} or null.
    function parse(u) {
      var suffix = '';
      var qi = u.search(/[?#]/);
      if (qi >= 0) { suffix = u.slice(qi); u = u.slice(0, qi); }
      var scheme = /^(file|chrome-extension|app):\/\//i.test(u);
      var abs;
      if (scheme) {
        // strip scheme://host, keep the pathname, which is virtual (/www/...)
        var pathname = u.replace(/^[a-z-]+:\/\/[^/]*/i, '');
        pathname = decodeURIComponent(pathname);
        if (/^\/[A-Za-z]:\//.test(pathname)) pathname = pathname.slice(1); // win drive (file://)
        var vrel = path.relative(virtualBase, pathname);
        if (vrel === '' || vrel.slice(0, 2) === '..') {
          // not under the virtual content root; treat pathname as real fs path
          abs = pathname;
        } else {
          abs = path.join(baseDir, vrel);
        }
      } else {
        var p = decodeURIComponent(u);
        abs = (p.charAt(0) === '/') ? p : path.join(baseDir, p);
      }
      var rel = path.relative(baseDir, abs);
      if (rel === '' || rel.slice(0, 2) === '..') return null; // outside content root
      return { abs: abs, rel: rel.split(path.sep).join('/'), absolute: scheme, suffix: suffix };
    }

    function fix(u) {
      if (typeof u !== 'string' || u === '') return u;
      var info;
      try { info = parse(u); } catch (e) { return u; }
      if (!info) return u;
      try { if (fs.existsSync(info.abs)) return u; } catch (e) { return u; } // exact case OK
      var actual = index[info.rel.toLowerCase()];
      if (!actual || actual === info.rel) { dbg('[casefix] MISS ' + info.rel); return u; }
      dbg('[casefix] REMAP ' + info.rel + ' -> ' + actual);
      // Return the corrected path in relative form; the browser resolves it
      // against the document base (the app's content root), same origin.
      return actual + info.suffix;
    }

    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
      if (arguments.length > 1) arguments[1] = fix(url);
      return origOpen.apply(this, arguments);
    };

    [window.HTMLImageElement, window.HTMLMediaElement].forEach(function (C) {
      if (!C) return;
      var d = Object.getOwnPropertyDescriptor(C.prototype, 'src');
      if (!d || !d.set || !d.get) return;
      Object.defineProperty(C.prototype, 'src', {
        get: d.get,
        set: function (v) { d.set.call(this, fix(v)); },
        configurable: true,
        enumerable: d.enumerable
      });
    });
  } catch (e) {
    try { console.error('[GameVault casefix] disabled:', e); } catch (_) {}
  }
})();
