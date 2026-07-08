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
  try {
    var fs = require('fs');
    var path = require('path');

    var baseDir = decodeURIComponent(window.location.pathname);
    baseDir = path.dirname(baseDir);
    // NW.js on Windows yields "/C:/..."; on Linux it's already a clean abs path.
    if (/^\/[A-Za-z]:\//.test(baseDir)) baseDir = baseDir.slice(1);

    // lower(relPath) -> real relPath (forward-slash), for files AND dirs.
    var index = Object.create(null);
    function walk(dir, rel) {
      var ents;
      try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
      for (var i = 0; i < ents.length; i++) {
        var name = ents[i].name;
        var childRel = rel ? rel + '/' + name : name;
        index[childRel.toLowerCase()] = childRel;
        if (ents[i].isDirectory()) walk(path.join(dir, name), childRel);
      }
    }
    walk(baseDir, '');

    // Given a request URL/path, return {abs, rel, isFileUrl, suffix} or null.
    function parse(u) {
      var suffix = '';
      var qi = u.search(/[?#]/);
      if (qi >= 0) { suffix = u.slice(qi); u = u.slice(0, qi); }
      var isFileUrl = /^file:\/\//i.test(u);
      var p = u;
      if (isFileUrl) {
        p = decodeURIComponent(u.replace(/^file:\/\//i, ''));
        if (/^\/[A-Za-z]:\//.test(p)) p = p.slice(1);
      }
      var abs = (p.charAt(0) === '/') ? p : path.join(baseDir, p);
      var rel = path.relative(baseDir, abs);
      if (rel === '' || rel.slice(0, 2) === '..') return null; // outside content root
      return { abs: abs, rel: rel.split(path.sep).join('/'), isFileUrl: isFileUrl, suffix: suffix };
    }

    function fix(u) {
      if (typeof u !== 'string' || u === '') return u;
      var info;
      try { info = parse(u); } catch (e) { return u; }
      if (!info) return u;
      try { if (fs.existsSync(info.abs)) return u; } catch (e) { return u; } // exact case OK
      var actual = index[info.rel.toLowerCase()];
      if (!actual || actual === info.rel) return u; // no better match
      if (info.isFileUrl) {
        return 'file://' + encodeURI(path.join(baseDir, actual)) + info.suffix;
      }
      return actual + info.suffix; // preserve relative form (resolves against document base)
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
