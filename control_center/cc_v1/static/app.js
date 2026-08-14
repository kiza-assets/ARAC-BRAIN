/* ==========================================================================
   ARAC — Control Center v1 · LE COCKPIT
   --------------------------------------------------------------------------
   Poste de pilotage, pas tableau de bord. Ouvert le matin, laissé ouvert.

   TROIS RÈGLES TIENNENT TOUT CE FICHIER
   -------------------------------------
   1. Aucun chiffre n'est écrit ici. Chaque valeur affichée provient d'un
      `fetch` vers /cc/v1/*. Quand l'API ne répond pas, l'écran dit qu'elle ne
      répond pas — il n'invente rien, il ne met pas zéro.

   2. Aucune arithmétique métier ici. Pas de somme, pas de moyenne, pas de
      ratio, pas de pourcentage. Les pourcentages affichés sont ceux que le SQL
      a produits ; ce fichier ne fait que les mettre en forme (séparateur de
      milliers, date relative, largeur d'une barre). Sélectionner, trier et
      filtrer sur une colonne servie par le moteur reste de la présentation :
      aucune valeur nouvelle n'en sort.

   3. Aucune phrase d'événement n'est écrite ici. Le flux compose ses lignes à
      partir du `message_catalog` servi par /cc/v1/stream/catalog. Une clé
      inconnue s'affiche « [événement inconnu : <type>] » — jamais un texte
      qu'on aurait deviné.

   CE QUE LE CODE A LE DROIT DE DÉCIDER
   -----------------------------------
   La FORME d'un maillon (franchi / en cours / en attente / échoué /
   indisponible) est déduite de champs servis par le moteur — `mesurable`,
   `objets`, `perte`, ou l'état `state` de la route des conversations. La règle
   est écrite une seule fois (`linkShape`), affichée dans la légende à l'écran,
   et ne produit aucun nombre.
   ========================================================================== */

(function () {
  'use strict';

  var API = '/cc/v1';

  /* =======================================================================
     0 · OUTILS — DOM, formatage. Rien ici ne touche au sens des données.
     ======================================================================= */

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = String(v);
        else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
        else n.setAttribute(k, String(v));
      }
    }
    append(n, kids);
    return n;
  }

  function append(n, kids) {
    if (kids === null || kids === undefined || kids === false) return n;
    if (Array.isArray(kids)) {
      for (var i = 0; i < kids.length; i++) append(n, kids[i]);
      return n;
    }
    n.appendChild(kids instanceof Node ? kids : document.createTextNode(String(kids)));
    return n;
  }

  /* `frag()` retiré le 2026-08-05 : aucun appel dans le fichier, aucun export
     (tout vit dans une IIFE). Du code non exécuté dans un fichier qu'on audite
     ligne à ligne coûte plus qu'il ne sert. */
  function clear(n) { while (n && n.firstChild) n.removeChild(n.firstChild); return n; }
  function $(sel) { return document.querySelector(sel); }

  /* ---- formatage de nombres : présentation seule --------------------- */

  var NF = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 3 });

  function fmtNum(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number' && isFinite(v)) return NF.format(v);
    if (typeof v === 'boolean') return v ? 'oui' : 'non';
    return String(v);
  }

  /* ---- dates : absolues en monospace, relatives en prose ------------- */

  var RTF = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' });
  var DTF = new Intl.DateTimeFormat('fr-FR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  });
  var TF = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  function ms(iso) { var t = Date.parse(iso); return isFinite(t) ? t : null; }
  function fmtStamp(iso) { var t = ms(iso); return t === null ? '—' : DTF.format(new Date(t)); }
  function fmtClock(iso) { var t = ms(iso); return t === null ? '—' : TF.format(new Date(t)); }

  function fmtRel(iso) {
    var t = ms(iso);
    if (t === null) return '—';
    var s = (t - Date.now()) / 1000;
    var a = Math.abs(s);
    if (a < 45) return RTF.format(Math.round(s), 'second');
    if (a < 3600) return RTF.format(Math.round(s / 60), 'minute');
    if (a < 86400) return RTF.format(Math.round(s / 3600), 'hour');
    if (a < 2592000) return RTF.format(Math.round(s / 86400), 'day');
    return RTF.format(Math.round(s / 2592000), 'month');
  }

  function fmtCell(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtStamp(v);
    if (typeof v === 'object') return JSON.stringify(v);
    return fmtNum(v);
  }

  function cut(s, n) {
    if (s === null || s === undefined) return '';
    s = String(s);
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  /* =======================================================================
     1 · ACCÈS À L'API — ne lève jamais, rend toujours un état lisible
     ======================================================================= */

  function get(path) {
    return fetch(path, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (r.status === 401) return { ok: false, status: 401, reason: 'session expirée ou absente' };
        if (!r.ok) return { ok: false, status: r.status, reason: 'réponse HTTP ' + r.status };
        return r.json().then(function (d) { return { ok: true, status: r.status, data: d }; },
          function () { return { ok: false, status: r.status, reason: 'réponse illisible' }; });
      })
      .catch(function (e) {
        return { ok: false, status: 0, reason: 'API injoignable (' + (e && e.name ? e.name : 'erreur réseau') + ')' };
      });
  }

  function qs(obj) {
    var parts = [];
    for (var k in obj) {
      if (!Object.prototype.hasOwnProperty.call(obj, k)) continue;
      var v = obj[k];
      if (v === null || v === undefined || v === '') continue;
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
    }
    return parts.length ? '?' + parts.join('&') : '';
  }

  /* =======================================================================
     2 · ÉTAT DU CLIENT — ce qui a été reçu, jamais ce qui a été deviné
     ======================================================================= */

  var S = {
    metrics: null,          // Map clé -> enveloppe de métrique servie
    metricsError: null,
    catalog: null,          // /cc/v1/catalog
    status: null,           // /cc/v1/status  (le cockpit vu par lui-même)
    stream: null,           // /cc/v1/stream/state
    msgCatalog: null,       // gabarits de phrases
    transport: null,
    events: [],             // anneau local d'affichage
    lastEventId: null,
    mode: 'init',           // init | sse | poll | down
    evidenceSql: {},        // preuves « requête source » enregistrées par les vues
    route: null,
    /* Un écran peut demander à recevoir les faits SANS être reconstruit : il
       pose son crochet ici et décide lui-même quoi en faire. C'est ce qui
       permet à la cascade d'insérer une nouveauté en tête sans arracher le
       focus ni déplacer ce que le lecteur est en train de lire. */
    liveHook: null
  };

  function metric(key) {
    if (!S.metrics) return null;
    return S.metrics.get(key) || null;
  }

  function metricsOf(domain) {
    var out = [];
    if (!S.metrics) return out;
    S.metrics.forEach(function (m) { if (m.domain === domain) out.push(m); });
    return out;
  }

  function loadMetrics() {
    return get(API + '/metrics').then(function (r) {
      if (!r.ok) { S.metricsError = r.reason; S.metrics = S.metrics || new Map(); return; }
      var map = new Map();
      var items = (r.data && r.data.items) || [];
      for (var i = 0; i < items.length; i++) map.set(items[i].key, items[i]);
      S.metrics = map;
      S.metricsError = null;
    });
  }

  /* =======================================================================
     3 · FRAGMENTS PARTAGÉS
     ======================================================================= */

  var GLYPH = { ok: '·', warn: '▲', critical: '■', unavailable: '◇' };

  function glyph(state) {
    return el('span', { class: 'glyph', 'data-state': state || 'unavailable', 'aria-hidden': 'true',
      text: GLYPH[state] || GLYPH.unavailable });
  }

  function stateChip(state, label) {
    return el('span', { class: 'chip', 'data-state': state || 'unavailable' },
      [glyph(state), el('span', { text: label || state || 'indisponible' })]);
  }

  /* Le bloc d'ABSENCE : raison, geste de déblocage, substitut.
     Une donnée absente n'est jamais un zéro — et elle a droit à une forme. */
  function naBlock(o) {
    var rows = [];
    if (o.reason) rows.push(el('dt', { text: 'raison' }), el('dd', { text: o.reason }));
    if (o.gesture) rows.push(el('dt', { text: 'geste' }), el('dd', { class: 'mono', text: o.gesture }));
    if (o.substitute) rows.push(el('dt', { text: 'substitut' }), el('dd', { text: o.substitute }));
    if (o.impact) {
      rows.push(el('dt', { text: 'impact' }),
        el('dd', { text: Array.isArray(o.impact) ? o.impact.join(' · ') : String(o.impact) }));
    }
    if (o.source) rows.push(el('dt', { text: 'source' }), el('dd', { class: 'mono', text: o.source }));
    return el('div', { class: 'na-block' }, [
      el('div', { class: 'na-title' }, [glyph('unavailable'), el('span', { text: o.title || 'Indisponible' })]),
      rows.length ? el('dl', { class: 'na-row' }, rows) : null
    ]);
  }

  function emptyBlock(title, why) {
    return el('div', { class: 'empty' }, [
      el('div', { class: 'strong', text: title }),
      why ? el('div', { class: 'small', text: why }) : null
    ]);
  }

  function sectionHead(title, right) {
    return el('div', { class: 'section-head' }, [
      el('h2', { class: 'section-title', text: title }),
      right || null
    ]);
  }

  function section(title, right, body) {
    return el('section', { class: 'section' }, [sectionHead(title, right), body]);
  }

  /* ---- seuils déclarés : affichés tels quels, jamais jugés ici -------- */

  function targetText(t) {
    if (!t) return null;
    var down = (t.direction || 'down') === 'down';
    var sign = down ? '≥ ' : '≤ ';
    var bits = [];
    if (t.warn !== null && t.warn !== undefined) bits.push('alerte ' + sign + fmtNum(t.warn));
    if (t.critical !== null && t.critical !== undefined) bits.push('critique ' + sign + fmtNum(t.critical));
    if (!bits.length) return null;
    return 'seuils déclarés : ' + bits.join(' · ') + (down ? ' (une valeur haute est mauvaise)' : ' (une valeur basse est mauvaise)');
  }

  /* ---- la valeur d'une métrique, cliquable jusqu'à sa preuve ---------- */

  function metricValueText(m) {
    if (!m) return '—';
    if (m.value === null || m.value === undefined) return '—';
    return fmtNum(m.value);
  }

  function metricCard(key, roleLabel) {
    var m = metric(key);
    if (!m) {
      return el('div', { class: 'card', 'data-state': 'unavailable' }, [
        el('div', { class: 'card-label', text: roleLabel || key }),
        el('div', { class: 'card-value', text: '—' }),
        el('div', { class: 'card-foot' }, [glyph('unavailable'),
          el('span', { class: 'card-key', text: 'clé absente du registre' })])
      ]);
    }
    var st = m.state || 'unavailable';
    var title = m.definition + (m.formula ? '\n\nformule : ' + m.formula : '') +
      (targetText(m.target) ? '\n' + targetText(m.target) : '') +
      '\n\nfenêtre : ' + m.window + ' · domaine : ' + m.domain +
      '\n\nun clic ouvre la preuve';
    var val = el('div', { class: 'card-value' }, [
      el('span', { text: metricValueText(m) }),
      m.unit ? el('span', { class: 'unit', text: m.unit }) : null
    ]);
    return el('button', {
      class: 'card q', type: 'button', 'data-state': st, 'data-metric': m.key,
      title: title, 'aria-label': m.label + ' — ouvrir la preuve'
    }, [
      el('div', { class: 'card-label', text: roleLabel || m.label }),
      val,
      el('div', { class: 'card-foot' }, [
        glyph(st),
        el('span', { class: 'card-key', text: m.key }),
        el('span', { class: 'evidence-cue', text: '↗ preuve' })
      ]),
      (m.state === 'unavailable' && m.reason)
        ? el('div', { class: 'tiny faint', text: m.reason }) : null
    ]);
  }

  function metricGrid(list) {
    var cards = list.map(function (m) { return metricCard(m.key, null); });
    return el('div', { class: 'cards' }, cards);
  }

  /* ---- barre proportionnelle : la largeur EST le pourcentage servi ---- */

  function bar(pct, tone) {
    var b = el('span', { class: 'bar', 'data-tone': tone || '' }, el('i', {}));
    if (typeof pct === 'number' && isFinite(pct)) b.firstChild.style.width = pct + '%';
    return b;
  }

  /* ---- tableaux génériques ------------------------------------------- */

  function dataTable(cols, rows, opts) {
    opts = opts || {};
    /* `opts.empty` : un tableau à zéro ligne n'explique rien. Une liste paginée
       au-delà de sa dernière page rendait un `<table>` sans corps — ni tableau,
       ni explication. Quand l'appelant sait quoi dire de ce vide, on le dit. */
    if (!rows.length && opts.empty) return emptyBlock(opts.empty[0], opts.empty[1]);
    var thead = el('thead', {}, el('tr', {}, cols.map(function (c) {
      return el('th', { class: c.num ? 'num' : (c.nowrap ? 'nowrap' : ''), text: c.label });
    })));
    var body = el('tbody', {}, rows.map(function (r) {
      var tr = el('tr', {}, cols.map(function (c) {
        var v = c.cell ? c.cell(r) : r[c.field];
        var cls = (c.num ? 'num ' : '') + (c.mono ? 'mono ' : '') + (c.wrap ? 'wrap ' : '') + (c.cls || '');
        if (v instanceof Node) return el('td', { class: cls }, v);
        if (v === null || v === undefined) return el('td', { class: cls + ' na', text: '—' });
        return el('td', { class: cls, text: c.raw ? String(v) : fmtCell(v) });
      }));
      if (opts.href && opts.href(r)) {
        /* Une ligne n'est cliquable que si le moteur a servi de quoi l'ouvrir.
           Une destination non résolue ne fabrique pas un lien mort.

           CE QUI ÉTAIT FAUX : la ligne n'avait qu'un gestionnaire de clic. Les 22
           tableaux navigables du cockpit n'étaient donc atteignables qu'à la souris
           — ni `tabindex`, ni `role`, ni clavier — alors que l'aide affiche en
           toutes lettres « Le cockpit se conduit sans souris ». La seule affordance
           était `cursor: pointer`, invisible au clavier comme à l'impression.
           CE QUE CETTE VERSION GARANTIT : la ligne est dans l'ordre de tabulation,
           s'annonce comme un lien, s'ouvre à Entrée, et reçoit le liseré lilas du
           focus (règle globale `:focus-visible` de ds.css). La promesse de l'aide
           redevient vraie. */
        var open = function () { var dest = opts.href(r); if (dest) go(dest); };
        tr.className = 'row-link';
        tr.setAttribute('tabindex', '0');
        tr.setAttribute('role', 'link');
        tr.addEventListener('click', function (ev) {
          if (ev.target && ev.target.closest && ev.target.closest('button,a')) return;
          open();
        });
        tr.addEventListener('keydown', function (ev) {
          /* Entrée seulement : la barre d'espace fait défiler la page, la lui
             prendre casserait la lecture d'un long tableau. */
          if (ev.key !== 'Enter') return;
          if (ev.target !== tr) return;   /* un bouton dans la ligne garde sa touche */
          ev.preventDefault();
          open();
        });
      }
      return tr;
    }));
    return el('div', { class: 'table-wrap' }, el('table', { class: 'data' }, [thead, body]));
  }

  /* =======================================================================
     4 · TIROIR DE PREUVE — la promesse centrale
     Depuis n'importe quel chiffre : définition, formule, SQL rejouable,
     lignes sources.
     ======================================================================= */

  var drawer, scrim, drawerTitle, drawerEyebrow, drawerBody, lastFocus = null;

  function openDrawer() {
    drawer.setAttribute('data-open', '1');
    scrim.setAttribute('data-open', '1');
    drawer.setAttribute('aria-hidden', 'false');
    lastFocus = document.activeElement;
    var c = drawer.querySelector('.drawer-close');
    if (c) c.focus();
  }

  function closeDrawer() {
    drawer.setAttribute('data-open', '0');
    scrim.setAttribute('data-open', '0');
    drawer.setAttribute('aria-hidden', 'true');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
    lastFocus = null;
  }

  function sqlBlock(label, sql) {
    var pre = el('pre', { class: 'sql', text: sql });
    var btn = el('button', { class: 'copy', type: 'button', text: 'copier' });
    btn.addEventListener('click', function () {
      var done = function () { btn.textContent = 'copié'; btn.setAttribute('data-done', '1'); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(sql).then(done, function () { selectNode(pre); });
      } else { selectNode(pre); }
    });
    return el('div', { class: 'stack' }, [
      el('div', { class: 'sql-head' }, [el('span', { class: 'eyebrow', text: label }), btn]),
      pre
    ]);
  }

  function selectNode(n) {
    var r = document.createRange(); r.selectNodeContents(n);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  }

  function drawerShell(eyebrow, title) {
    drawerEyebrow.textContent = eyebrow;
    drawerTitle.textContent = title;
    clear(drawerBody);
    openDrawer();
  }

  /* `win` : la fenêtre sous laquelle le chiffre a été LU.
     CE QUI ÉTAIT FAUX : l'écran « Aujourd'hui » affiche un chiffre de 7 ou 30 jours,
     et le tiroir ouvrait /cc/v1/evidence/<clé>, dont le SQL code en dur
     `interval '24 hours'`. La preuve et le chiffre ne parlaient pas de la même
     période, sans que rien ne le signale. La route /cc/v1/today/evidence/{clé},
     bâtie exactement pour cela, n'était appelée par aucun écran.
     CE QUE CETTE VERSION GARANTIT : une preuve ouverte depuis une carte de fenêtre
     interroge la route de fenêtre, avec la fenêtre de la carte. Les deux routes
     rendent la même enveloppe — le corps du tiroir est inchangé. */
  function openMetricEvidence(key, win) {
    var m = metric(key);
    drawerShell('preuve · ' + key + (win ? ' · fenêtre ' + win : ''), (m && m.label) || key);
    drawerBody.appendChild(el('div', { class: 'spin', text: 'lecture des lignes sources…' }));
    var url = win
      ? API + '/today/evidence/' + encodeURIComponent(key) + qs({ window: win, limit: 200 })
      : API + '/evidence/' + encodeURIComponent(key) + '?limit=200';
    get(url).then(function (r) {
      clear(drawerBody);
      if (!r.ok) {
        drawerBody.appendChild(naBlock({
          title: 'La preuve n\'a pas pu être lue',
          reason: r.reason,
          gesture: 'vérifier que le Control Center joint PostgreSQL en lecture seule',
          substitute: 'aucun — une métrique sans preuve ne doit pas être crue'
        }));
        return;
      }
      var d = r.data || {};
      /* CE QUI ÉTAIT FAUX : ce test ne portait que sur `d.state`, l'état de la
         REQUÊTE DE PREUVE — toujours « ok », puisque la requête d'une métrique
         indisponible constate justement l'absence et réussit. L'état de la
         MESURE vit dans l'enveloppe du registre (`m.state`). La branche était
         donc morte pour les 11 métriques indisponibles du registre : « Liens
         créés · — liens » s'ouvrait comme une preuve ordinaire, sans glyphe ◇,
         sans raison, et le `gesture` comme le `substitute` servis étaient jetés.
         CE QUE CETTE VERSION GARANTIT : l'indisponibilité est portée par le
         bandeau du tiroir et par un bloc d'absence complet ; les lignes que la
         base répond restent montrées, mais sous leur vrai intitulé — le constat
         de l'absence, pas la preuve d'une valeur. */
      var naState = (d.state === 'unavailable') || (m && m.state === 'unavailable');
      if (naState) {
        drawerEyebrow.textContent = 'preuve · ' + key + (win ? ' · fenêtre ' + win : '')
          + ' · ' + GLYPH.unavailable + ' ' + ((m && m.state) || d.state || 'unavailable');
        drawerBody.appendChild(naBlock({
          title: 'Mesure jamais prise — ce n\'est pas un zéro',
          reason: (m && m.reason) || d.reason || 'raison non fournie',
          gesture: (m && m.gesture) || null,
          substitute: (m && m.substitute) || null,
          source: (m && m.unit) ? (key + ' · ' + m.unit) : key
        }));
        if (m && m.detail) drawerBody.appendChild(el('p', { class: 'tiny faint', text: m.detail }));
        if (d.definition) {
          drawerBody.appendChild(el('dl', { class: 'def-list' }, [
            el('div', { class: 'def' }, [el('dt', { text: 'ce que la métrique dirait' }), el('dd', { text: d.definition })]),
            el('div', { class: 'def' }, [el('dt', { text: 'formule' }), el('dd', { class: 'mono', text: d.formula || '—' })])
          ]));
        }
        drawerBody.appendChild(sqlBlock('sql de la valeur — rejouable tel quel', d.value_sql || '—'));
        drawerBody.appendChild(sqlBlock('sql du constat — rejouable tel quel', d.sql || '—'));
        if ((d.rows || []).length) {
          drawerBody.appendChild(el('div', { class: 'stack' }, [
            el('div', { class: 'eyebrow', text: 'ce que la base répond, constaté maintenant' }),
            dataTable((d.columns || []).map(function (c, i) {
              return { label: c, num: false, cell: function (r2) { return r2[i]; } };
            }), d.rows, {})
          ]));
        }
        return;
      }
      var defs = el('dl', { class: 'def-list' }, [
        el('div', { class: 'def' }, [el('dt', { text: 'ce que la métrique dit' }), el('dd', { text: d.definition || '—' })]),
        el('div', { class: 'def' }, [el('dt', { text: 'formule' }), el('dd', { class: 'mono', text: d.formula || '—' })]),
        m && targetText(m.target) ? el('div', { class: 'def' }, [
          el('dt', { text: 'seuils' }), el('dd', { class: 'small', text: targetText(m.target) })]) : null,
        el('div', { class: 'def' }, [el('dt', { text: 'ces lignes représentent' }), el('dd', { text: d.evidence_label || '—' })])
      ]);
      /* L'état de la mesure est porté À CÔTÉ du chiffre, pas seulement dans la
         couleur d'une carte restée sur l'écran d'en dessous. Un tiroir de preuve
         qui n'énonce pas l'état de ce qu'il prouve laisse le lecteur deviner. */
      var head = el('div', { class: 'stack' }, [
        m ? el('div', {}, [
          el('span', { class: 'card-value', text: metricValueText(m) }),
          m.unit ? el('span', { class: 'unit', text: m.unit }) : null,
          el('span', { style: 'margin-left:12px' }, stateChip(m.state, m.state || 'état non servi')),
          el('span', { class: 'ts', style: 'margin-left:12px', text: 'lu ' + fmtRel(m.computed_at) })
        ]) : null,
        (d.window || d.window_label) ? el('p', { class: 'tiny faint',
          text: 'fenêtre de cette preuve : ' + (d.window_label || d.window) }) : null,
        defs
      ]);
      var rows = d.rows || [];
      var cols = (d.columns || []).map(function (c, i) {
        return { label: c, num: false, cell: function (r) { return r[i]; } };
      });
      drawerBody.appendChild(head);
      drawerBody.appendChild(sqlBlock('sql de la valeur — rejouable tel quel', d.value_sql || '—'));
      drawerBody.appendChild(sqlBlock('sql de la preuve — rejouable tel quel', d.sql || '—'));
      drawerBody.appendChild(el('div', { class: 'stack' }, [
        el('div', { class: 'eyebrow', text: 'lignes sources · ' + fmtNum(d.row_count) + (d.truncated ? ' (tronqué à ' + fmtNum(d.limit) + ')' : '') }),
        rows.length ? dataTable(cols, rows, {}) : emptyBlock('Aucune ligne source', 'la requête de preuve n\'a rien retourné : ce n\'est pas un zéro, c\'est une absence de lignes.')
      ]));
    });
  }

  /* Preuve « requête source » : les routes de navigation servent le SQL qui a
     produit la page. Pas de lignes séparées à rejouer — la page EST le
     résultat. On l'affiche donc tel quel, rejouable au terminal. */
  function openSqlEvidence(id) {
    var e = S.evidenceSql[id];
    if (!e) { return; }
    drawerShell('preuve · requête source', e.label || 'La requête qui a produit cet écran');
    drawerBody.appendChild(el('p', { class: 'lede small', text: 'Cette route ne passe pas par le registre des métriques : sa preuve est la requête elle-même. Elle est rejouable à l\'identique depuis un terminal, donc opposable.' }));
    drawerBody.appendChild(sqlBlock('sql servi par la route', e.sql || '—'));
    if (e.queries) {
      for (var k in e.queries) {
        if (!Object.prototype.hasOwnProperty.call(e.queries, k)) continue;
        drawerBody.appendChild(sqlBlock('sql · ' + k, e.queries[k]));
      }
    }
  }

  function registerSqlEvidence(id, ev) {
    if (!ev) return null;
    S.evidenceSql[id] = ev;
    return el('button', { class: 'pill', type: 'button', 'data-sql': id, text: '↗ requête source' });
  }

  /* =======================================================================
     5 · LA CHAÎNE DES SIX MAILLONS
     ======================================================================= */

  /* Règle de forme — unique, affichée à l'écran, ne produit aucun nombre.
     Elle ne lit que des champs servis par le moteur.

     CE QUI ÉTAIT FAUX (corrigé le 2026-08-05) : `perte === null` rendait `done`,
     c'est-à-dire piste pleine à 100 % et pastille verte. Or le moteur sert
     `perte = null` quand il N'A RIEN MESURÉ — le maillon « retrouvées »
     (969 atomes servis, unité changée, donc aucune perte calculable) s'affichait
     « franchi, 100 % ». Une absence de mesure rendue en succès total : l'inverse
     exact de la règle « une donnée absente n'est jamais un zéro ».

     CE QUE CETTE VERSION GARANTIT : seule une perte MESURÉE et nulle vaut
     « franchi ». Une perte non servie devient `unmeasured` — piste vide, mot
     propre, aucun vert. Le maillon garde son compte d'objets, qui, lui, est mesuré. */
  function linkShape(row) {
    if (row.mesurable === false) return 'unavailable';
    if (row.objets === null || row.objets === undefined) return 'unavailable';
    if (row.perte === null || row.perte === undefined) return 'unmeasured';
    if (row.perte === 0) return 'done';
    return 'partial';
  }

  // Vocabulaire d'état des maillons — DOIT couvrir tout ce que le BFF publie.
  // Le BFF sert 7 états ; n'en connaître que 5 et rabattre le reste sur
  // « en attente » masquait 104 conversations ANALYSÉES SANS AUCUN ATOME
  // (état `empty`) — c'est-à-dire le signal produit le plus important du cockpit,
  // affiché comme « pas encore traité ». Toute nouvelle valeur servie doit être
  // ajoutée ici ; `linkShape()` signale explicitement celles qu'il ne connaît pas.
  //
  // `error` (2026-08-05) : c'est l'état que /cc/v1/conversations sert RÉELLEMENT
  // pour une curation en erreur (entities.py `_CHAIN_SQL`, CASE … WHEN 'error').
  // `failed` n'est jamais émis par cette route ; il est conservé parce qu'une autre
  // route peut l'émettre, et parce qu'un vocabulaire ne se rétrécit pas sur une
  // observation. Les 4 conversations en erreur affichaient « état inconnu : error »
  // en ambre pointillé — un défaut de contrat rendu comme un doute de l'interface.
  // `unmeasured` : voir `linkShape()` — le moteur n'a pas mesuré, on ne conclut pas.
  var LINK_WORD = {
    done: 'franchi', partial: 'en cours', pending: 'en attente',
    failed: 'échoué', error: 'échoué — erreur de curation',
    unavailable: 'indisponible', unmeasured: 'perte non mesurée',
    empty: 'sans matière', skipped: 'écartée'
  };

  // Alias de FORME : deux états distincts peuvent partager un dessin. Le mot reste
  // celui de l'état servi (`chainWord`), seul le rendu est mutualisé. Sans cet
  // alias, ajouter `error` à LINK_WORD l'aurait fait tomber sur le style de base
  // — piste vide, teinte neutre — soit « rien ne s'est passé » là où le cycle a
  // échoué. Il porte donc le dessin de `failed` : hachures rouges, pastille.
  var LINK_FORM_ALIAS = { error: 'failed' };

  // Description de la FORME rendue, par état. Sert la légende (voir chainLegend) :
  // la légende se construit à partir de LINK_WORD, donc une clé ajoutée ci-dessus
  // apparaît d'office à l'écran. Une clé sans description est signalée, pas tue.
  var LINK_FORM_WORD = {
    done: 'segment plein, pastille pleine',
    partial: 'segment partiel, losange plein',
    pending: 'piste vide, anneau',
    failed: 'hachures, pastille',
    error: 'hachures, pastille — même dessin que « échoué »',
    unavailable: 'pointillé, losange creux, teinte neutre',
    unmeasured: 'piste vide, marque creuse, teinte neutre — le compte reste affiché',
    empty: 'piste pleine en teinte neutre, carré creux',
    skipped: 'piste barrée en diagonale, marque barrée',
    unknown: 'pointillé ambre, anneau pointillé'
  };

  // Traduit un état servi en forme rendue. Un état inconnu n'est JAMAIS silencieusement
  // assimilé à « en attente » : il est rendu `unknown` et nommé, pour qu'une divergence
  // de contrat entre le moteur et l'interface se voie au lieu de mentir.
  function chainShape(state) {
    if (!Object.prototype.hasOwnProperty.call(LINK_WORD, state)) return 'unknown';
    return LINK_FORM_ALIAS[state] || state;
  }
  function chainWord(state) {
    return LINK_WORD[state] || ('état inconnu : ' + state);
  }

  function chainFromFunnel(ev) {
    var rows = ev.rows || [];
    var cols = ev.columns || [];
    var ix = {};
    for (var i = 0; i < cols.length; i++) ix[cols[i]] = i;
    var links = rows.map(function (r) {
      return {
        rang: r[ix.rang], maillon: r[ix.maillon], unite: r[ix.unite],
        objets: r[ix.objets], perte: r[ix.perte],
        conversion_pct: r[ix.conversion_pct], mesurable: r[ix.mesurable],
        lecture: r[ix.lecture]
      };
    });
    return links;
  }

  function chainNode(links, onProof) {
    return el('div', { class: 'chain' }, links.map(function (L) {
      var shape = linkShape(L);
      var fill = el('i', { class: 'link-fill' });
      if (shape === 'done') fill.style.width = '100%';
      else if (shape === 'partial' && typeof L.conversion_pct === 'number') fill.style.width = L.conversion_pct + '%';
      var node = el('button', {
        class: 'link q', type: 'button', 'data-link': shape,
        title: (L.lecture || '') + '\n\nforme : ' + LINK_WORD[shape],
        'aria-label': L.maillon + ' — ' + LINK_WORD[shape]
      }, [
        el('div', { class: 'link-head' }, [
          el('span', { class: 'link-mark', 'aria-hidden': 'true' }),
          el('span', { class: 'link-name', text: L.maillon })
        ]),
        el('div', { class: 'link-track' }, fill),
        el('div', { class: 'link-value' }, [
          el('span', { text: L.objets === null || L.objets === undefined ? '—' : fmtNum(L.objets) }),
          el('span', { class: 'unit', text: L.unite || '' })
        ]),
        typeof L.conversion_pct === 'number'
          ? el('div', { class: 'link-note', text: 'conversion ' + fmtNum(L.conversion_pct) + ' %' })
          : el('div', { class: 'link-note', text: LINK_WORD[shape] || shape }),
        (typeof L.perte === 'number' && L.perte > 0)
          ? el('div', { class: 'link-loss', text: '− ' + fmtNum(L.perte) + ' ' + (L.unite || '') })
          : null
      ]);
      if (onProof) node.addEventListener('click', onProof);
      return node;
    }));
  }

  function chainMini(chain) {
    return el('span', { class: 'chain-mini' }, (chain || []).map(function (c) {
      return el('span', {
        class: 'cm', 'data-link': chainShape(c.state),
        title: c.label + ' — ' + chainWord(c.state) + (c.reason ? ' · ' + c.reason : '')
      });
    }));
  }

  function chainFull(chain) {
    return el('div', { class: 'chain' }, (chain || []).map(function (c) {
      var shape = chainShape(c.state);
      var fill = el('i', { class: 'link-fill' });
      if (shape === 'done') fill.style.width = '100%';
      else if (shape === 'partial' && typeof c.detail === 'number') fill.style.width = c.detail + '%';
      return el('div', {
        class: 'link', 'data-link': shape,
        title: (c.reason || '') + '\nsource : ' + (c.source || '—')
      }, [
        el('div', { class: 'link-head' }, [
          el('span', { class: 'link-mark', 'aria-hidden': 'true' }),
          el('span', { class: 'link-name', text: c.label })
        ]),
        el('div', { class: 'link-track' }, fill),
        el('div', { class: 'link-note', text: chainWord(c.state) }),
        (typeof c.detail === 'number')
          ? el('div', { class: 'link-value' }, el('span', { text: fmtNum(c.detail) })) : null,
        c.reason ? el('div', { class: 'tiny faint', text: c.reason }) : null,
        c.gesture ? el('div', { class: 'tiny mono faint', text: c.gesture }) : null
      ]);
    }));
  }

  /* LA LÉGENDE SE CONSTRUIT À PARTIR DU VOCABULAIRE, elle ne le recopie plus.
     CE QUI ÉTAIT FAUX : une liste écrite à la main documentait 5 formes sur 8 —
     dont `failed`, que le BFF n'émet pas — et taisait `empty` (« sans matière »),
     porté par 107 conversations sur 200 au maillon « Atomisée », c'est-à-dire le
     signal produit le plus important du cockpit, expliqué nulle part.
     CE QUE CETTE VERSION GARANTIT : toute clé ajoutée à LINK_WORD apparaît d'office
     dans la légende. Une clé sans description de forme est signalée à l'écran au
     lieu d'être omise — la divergence ne peut plus se réinstaller en silence. */
  function chainLegend() {
    var states = Object.keys(LINK_WORD);
    /* `unknown` n'est pas un état SERVI : c'est la forme que l'interface donne à
       un état qu'elle ne connaît pas. Il se documente donc, sans être du vocabulaire. */
    states.push('unknown');

    /* Découpé en rangées : `.chain` dispose ses maillons en colonnes de largeur
       égale — dix d'un coup les rendrait illisibles. */
    var ROW = 5;
    var rows = [];
    for (var i = 0; i < states.length; i += ROW) rows.push(states.slice(i, i + ROW));

    return el('div', { class: 'stack tiny faint' }, [
      el('div', { class: 'stack' }, rows.map(function (group) {
        return el('div', { class: 'chain' }, group.map(function (st) {
          var form = LINK_FORM_ALIAS[st] || st;
          return el('div', { class: 'link', 'data-link': form }, [
            el('div', { class: 'link-head' }, [
              el('span', { class: 'link-mark', 'aria-hidden': 'true' }),
              el('span', { class: 'link-name', text: st })
            ]),
            el('div', { class: 'link-track' }, el('i', {
              class: 'link-fill', style: form === 'done' ? 'width:100%' : (form === 'partial' ? 'width:55%' : '')
            })),
            el('div', { class: 'link-note', text: chainWord(st) }),
            el('div', { class: 'tiny faint', text: LINK_FORM_WORD[st] || 'forme non décrite — à documenter dans LINK_FORM_WORD' })
          ]);
        }));
      })),
      el('p', { class: 'tiny faint', text: 'Règle de forme de l\'entonnoir (aucun nombre n\'en sort) : un maillon non mesurable ou sans objet est INDISPONIBLE ; un maillon dont la perte n\'est pas servie est PERTE NON MESURÉE — ce n\'est ni un zéro, ni un succès ; un maillon dont la perte servie vaut zéro est FRANCHI ; un maillon dont le moteur rapporte une perte est EN COURS. Sur la chaîne d\'une conversation, l\'état est servi tel quel par le moteur : « sans matière » signifie lue et sans aucun atome produit, « écartée » retirée par décision, « échoué » interrompue par une erreur.' })
    ]);
  }

  /* =======================================================================
     6 · BANDEAU VITAL — cinq valeurs, jamais plus
     ======================================================================= */

  /* Le grand chiffre. On cherche d'abord une métrique du domaine « etat-general »
     — c'est là que vivrait un véritable indice de santé. À défaut, on affiche un
     SUBSTITUT DÉCLARÉ, et on le dit. Le jour où le registre publie l'indice,
     l'écran bascule seul, sans toucher à ce fichier. */
  var HEALTH_SUBSTITUTE = 'digestion_funnel_conversion';

  /* L'indice de santé se DÉSIGNE par sa clé, jamais par « la première métrique
     du domaine ». Prendre la première rencontrée affichait « V1 — Rappel »
     (4,1/100) sous le libellé « indice de santé » — un chiffre juste, sous un
     nom faux, à l'endroit le plus visible du produit. Le libellé fait la
     promesse ; c'est la clé qui doit la tenir. */
  var HEALTH_KEY = 'brain_health_index';

  function resolveHealth() {
    var chosen = metric(HEALTH_KEY);
    if (chosen) return { metric: chosen, substitute: false };
    var sub = metric(HEALTH_SUBSTITUTE);
    return { metric: sub, substitute: true };
  }

  /* Chaque emplacement porte un RÔLE (ce qu'on vient y chercher) et
     une métrique. L'étiquette affichée est celle de l'API, jamais un mot choisi
     ici : renommer « Rappels en confiance basse » en « score de rappel »
     inverserait le sens de la valeur sans qu'aucune donnée ne bouge. */
  var VITALS = [
    { role: 'Indice de santé', showRole: true, get: function () { var h = resolveHealth(); return h.metric; } },
    { role: 'Score de rappel', key: 'recall_low_band_ratio', subKey: 'recall_budget_stop_ratio', subWord: 'arrêts budget' },
    { role: 'File et résorption', key: 'curation_backlog', subKey: 'backlog_eta_days', subWord: 'résorption' },
    { role: 'Dernière activité', kind: 'stream' },
    { role: 'État de l\'IA payante', key: 'pipeline_tokens_per_cycle', subKey: 'pipeline_cycle_duration_p50', subWord: 'cycle médian' }
  ];

  function renderVitals() {
    var strip = $('#vital-strip');
    clear(strip);
    VITALS.forEach(function (v) {
      if (v.kind === 'stream') { strip.appendChild(vitalActivity()); return; }
      var m = v.get ? v.get() : metric(v.key);
      if (!m) {
        strip.appendChild(el('div', { class: 'vital', 'data-state': 'unavailable' }, [
          el('div', { class: 'vital-label', text: v.role }),
          el('div', { class: 'vital-value', text: '—' }),
          el('div', { class: 'vital-sub', text: 'aucune métrique ne porte cette constante' })
        ]));
        return;
      }
      var sub = v.subKey ? metric(v.subKey) : null;
      var subTxt = m.key;
      if (sub && sub.value !== null && sub.value !== undefined) {
        subTxt = (v.subWord ? v.subWord + ' ' : '') + fmtNum(sub.value) + ' ' + (sub.unit || '') + ' · ' + m.key;
      }
      if (v.showRole) {
        subTxt = (resolveHealth().substitute ? 'substitut déclaré · ' : '') + m.key;
      }
      strip.appendChild(el('button', {
        class: 'vital q', type: 'button', 'data-state': m.state || 'unavailable', 'data-metric': m.key,
        title: v.role + '\n\n' + m.label + ' — ' + m.definition + '\n\nun clic ouvre la preuve',
        'aria-label': v.role + ' : ' + m.label + ' — ouvrir la preuve'
      }, [
        el('div', { class: 'vital-label', text: v.showRole ? v.role : m.label }),
        el('div', { class: 'vital-value' }, [
          el('span', { text: metricValueText(m) }),
          m.unit ? el('span', { class: 'unit', text: m.unit }) : null
        ]),
        el('div', { class: 'vital-sub', text: subTxt })
      ]));
    });
  }

  function vitalActivity() {
    var st = S.stream;
    if (!st) {
      return el('div', { class: 'vital', 'data-state': 'unavailable' }, [
        el('div', { class: 'vital-label', text: 'Dernière activité' }),
        el('div', { class: 'vital-value', text: '—' }),
        el('div', { class: 'vital-sub', text: 'état du flux non lu' })
      ]);
    }
    var la = st.last_activity || {};
    var stamps = [];
    for (var k in la) {
      if (!Object.prototype.hasOwnProperty.call(la, k)) continue;
      var t = ms(la[k]);
      if (t !== null) stamps.push({ k: k, t: t, iso: la[k] });
    }
    stamps.sort(function (a, b) { return b.t - a.t; });
    var top = stamps.length ? stamps[0] : null;
    var next = st.next_cycle || {};
    return el('button', {
      /* Un cycle en cours n'est PAS une alerte : c'est le cerveau qui fait
         exactement ce pour quoi il existe. Peindre le travail en ambre et le
         repos en vert inversait le sens du bandeau permanent — l'écran
         s'allumait quand tout allait bien. Le travail se signale par le
         mouvement du flux, pas par une couleur d'alerte. */
      class: 'vital q', type: 'button', 'data-state': 'ok', 'data-view': 'activite',
      'data-activity': st.idle ? 'idle' : 'working',
      title: 'Le cerveau travaille quelques fois par jour. Entre deux cycles, le flux n\'émet rien : c\'est le comportement correct.\n\nrègle de repos : ' + (st.idle_rule || '—'),
      'aria-label': 'Dernière activité — ouvrir l\'écran Activité'
    }, [
      el('div', { class: 'vital-label', text: st.idle ? 'Au repos' : 'En cours' }),
      el('div', { class: 'vital-value', text: top ? fmtRel(top.iso) : '—' }),
      el('div', { class: 'vital-sub', text: (top ? top.k + ' · ' : '') + (next.at_utc ? 'prochain cycle ' + fmtRel(next.at_utc) : 'prochain cycle inconnu') })
    ]);
  }

  /* =======================================================================
     7 · ÉCRAN D'ACCUEIL — État général
     ======================================================================= */

  var HOME_CARDS = [
    'atoms_active', 'atoms_created_7d', 'last_atom_age_hours', 'conversations_total',
    'curation_backlog', 'backlog_eta_days', 'root_level_debt', 'dormant_knowledge',
    'recall_low_band_ratio', 'digestion_yield', 'quarantine_blast_radius', 'projects_coverage_ratio'
  ];

  function viewGeneral(host) {
    var h = resolveHealth();
    var m = h.metric;
    var st = m ? (m.state || 'unavailable') : 'unavailable';

    var figure;
    if (m) {
      figure = el('button', {
        class: 'health-figure q', type: 'button', 'data-metric': m.key,
        'aria-label': 'Indice de santé (' + m.label + ') — ouvrir la preuve'
      }, [
        el('div', { class: 'health-value' }, [
          el('span', { text: metricValueText(m) }),
          m.unit ? el('span', { class: 'unit', text: m.unit }) : null
        ]),
        el('div', { class: 'eyebrow', text: 'indice de santé' })
      ]);
    } else {
      figure = el('div', { class: 'health-figure' }, [
        el('div', { class: 'health-value', text: '—' }),
        el('div', { class: 'eyebrow', text: 'indice de santé' })
      ]);
    }

    var caption = el('div', { class: 'health-caption' }, [
      el('div', { class: 'health-name', text: m ? m.label : 'Aucun indice publié' }),
      el('p', { class: 'small', text: m ? m.definition : 'Le registre ne publie aucune métrique du domaine « etat-general ».' }),
      h.substitute ? el('div', { class: 'chip', 'data-state': 'unavailable' }, [
        glyph('unavailable'),
        el('span', { text: 'substitut déclaré — aucun indice de santé au registre' })
      ]) : null,
      h.substitute ? el('p', { class: 'tiny faint', text: 'Le cockpit ne calcule jamais un chiffre lui-même. Tant qu\'aucune métrique du domaine « etat-general » n\'existe, il affiche à sa place la seule mesure de bout en bout de la chaîne, nommée et traçable : ' + (m ? m.key : '—') + '. L\'ajout d\'un indice au registre remplacera ce substitut sans qu\'une ligne de ce cockpit change.' }) : null,
      m && m.computed_at ? el('div', { class: 'ts', text: 'lu ' + fmtRel(m.computed_at) + ' · ' + fmtStamp(m.computed_at) }) : null
    ]);

    host.appendChild(el('div', { class: 'health', 'data-state': st }, [figure, caption]));

    /* --- constantes vitales --- */
    host.appendChild(section('Constantes vitales',
      el('span', { class: 'tiny faint', text: 'chaque carte : sa définition au survol, sa preuve au clic' }),
      metricGrid(HOME_CARDS.map(function (k) { return metric(k) || { key: k }; }))));

    /* --- la chaîne des six maillons --- */
    var chainHost = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de la chaîne…' }));
    host.appendChild(section('La chaîne', el('span', { class: 'tiny faint', text: 'Détectée → Absorbée → Analysée → Atomisée → Reliée → Retrouvée' }), chainHost));

    /* --- le blocage principal --- */
    var blockHost = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'identification du maillon le plus coûteux…' }));
    host.appendChild(section('Blocage principal', null, blockHost));

    get(API + '/evidence/' + HEALTH_SUBSTITUTE + '?limit=10').then(function (r) {
      clear(chainHost); clear(blockHost);
      if (!r.ok || !r.data || r.data.state === 'unavailable') {
        var why = (r.data && r.data.reason) || (r.ok ? 'preuve indisponible' : r.reason);
        chainHost.appendChild(naBlock({ title: 'La chaîne n\'a pas pu être lue', reason: why,
          substitute: 'la chaîne d\'une conversation reste lisible sur sa fiche' }));
        blockHost.appendChild(naBlock({ title: 'Blocage non déterminable', reason: why }));
        return;
      }
      var links = chainFromFunnel(r.data);
      chainHost.appendChild(chainNode(links, function () { openMetricEvidence(HEALTH_SUBSTITUTE); }));
      chainHost.appendChild(el('div', { class: 'hr' }));
      chainHost.appendChild(chainLegend());

      /* Le blocage : le maillon dont le MOTEUR rapporte la plus grande perte.
         Trier sur une colonne servie n'est pas un calcul — aucune valeur
         nouvelle n'apparaît à l'écran. */
      var lossy = links.filter(function (L) { return typeof L.perte === 'number' && L.perte > 0; });
      lossy.sort(function (a, b) { return b.perte - a.perte; });
      if (!lossy.length) {
        blockHost.appendChild(emptyBlock('Aucune perte rapportée entre deux maillons',
          'le moteur ne rapporte aucune perte comparable d\'un maillon à l\'autre ; ce n\'est pas la preuve qu\'il n\'y en a pas, c\'est l\'absence de mesure.'));
      } else {
        var L = lossy[0];
        var backlog = metric('curation_backlog');
        var eta = metric('backlog_eta_days');
        var head = metric('digestion_queue_head_age_days');
        var resid = metric('digestion_residence_p95_days');
        var facts = [];
        function fact(k, m2) {
          if (!m2 || m2.value === null || m2.value === undefined) return;
          facts.push(el('button', { class: 'block-fact q', type: 'button', 'data-metric': m2.key,
            title: m2.definition + '\n\nun clic ouvre la preuve' }, [
            el('span', { class: 'k', text: k }),
            el('span', { class: 'v' }, [el('span', { text: fmtNum(m2.value) }), el('span', { class: 'unit', text: m2.unit || '' })])
          ]));
        }
        facts.push(el('div', { class: 'block-fact' }, [
          el('span', { class: 'k', text: 'matière retenue' }),
          el('span', { class: 'v' }, [el('span', { text: fmtNum(L.perte) }), el('span', { class: 'unit', text: L.unite || '' })])
        ]));
        fact('file', backlog);
        fact('tête de file', head);
        fact('séjour p95', resid);
        fact('résorption', eta);
        var headLine = el('div', { class: 'small muted', text: 'lecture de la tête de file…' });
        blockHost.appendChild(el('div', { class: 'block-main' }, [
          el('div', { class: 'block-title', text: 'Maillon « ' + L.maillon + ' » — c\'est là que la matière s\'arrête.' }),
          el('p', { class: 'small muted', text: L.lecture || '' }),
          el('div', { class: 'block-facts' }, facts),
          headLine,
          el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
            el('button', { class: 'pill', type: 'button', 'data-metric': HEALTH_SUBSTITUTE, text: '↗ preuve de l\'entonnoir' }),
            el('button', { class: 'pill', type: 'button', 'data-go': '#/conversations?status=pending&order=queue_rank', text: '→ la file, tête en premier' })
          ])
        ]));

        /* La date du blocage, et de quoi l'ouvrir : la conversation qui est
           réellement en tête de file, servie par /cc/v1/conversations. */
        get(API + '/conversations' + qs({ status: 'pending', order: 'queue_rank', limit: 1 })).then(function (rq) {
          clear(headLine);
          if (!rq.ok || !rq.data || !(rq.data.items || []).length) {
            headLine.appendChild(el('span', { class: 'tiny faint', text: 'tête de file non servie' }));
            return;
          }
          var c0 = rq.data.items[0];
          headLine.appendChild(el('span', { class: 'small muted', text: 'En tête depuis ' + fmtStamp(c0.content_date) + ' (' + fmtRel(c0.content_date) + ') — ' }));
          headLine.appendChild(el('button', {
            class: 'pill', type: 'button', 'data-go': '#/conversations/' + encodeURIComponent(c0.uid),
            text: '→ ' + cut(c0.title || c0.uid, 52)
          }));
        });
      }
    });
  }

  /* =======================================================================
     8 · ÉCRAN ACTIVITÉ — le repos est une PRÉSENCE, pas un vide
     ======================================================================= */

  function viewActivite(host) {
    var st = S.stream;
    var restHost = el('div', { class: 'stack' });
    if (!st) {
      restHost.appendChild(naBlock({ title: 'État du flux non lu', reason: 'la route /cc/v1/stream/state n\'a pas répondu' }));
    } else {
      var next = st.next_cycle || {};
      var la = st.last_activity || {};
      var rows = [];
      for (var k in la) {
        if (!Object.prototype.hasOwnProperty.call(la, k)) continue;
        rows.push({ quoi: k, quand: la[k] });
      }
      rows.sort(function (a, b) { return (ms(b.quand) || 0) - (ms(a.quand) || 0); });

      restHost.appendChild(el('div', { class: 'grid-2' }, [
        el('div', { class: 'stack' }, [
          el('div', { class: 'eyebrow', text: st.idle ? 'au repos' : 'passage en cours' }),
          el('div', { class: 'card-value', text: next.at_utc ? fmtRel(next.at_utc) : '—' }),
          el('div', { class: 'small muted', text: next.at_utc ? 'prochain cycle · créneau ' + (next.slot || '?') + ' · ' + (next.local_time || '') + ' (' + ((st.schedule || {}).timezone || 'local') + ')' : 'prochain cycle inconnu' }),
          el('div', { class: 'ts', text: next.at_utc ? fmtStamp(next.at_utc) : '' }),
          el('p', { class: 'tiny faint', text: st.idle_rule || '' })
        ]),
        el('div', { class: 'stack' }, [
          el('div', { class: 'eyebrow', text: 'dernier signe de vie, par source' }),
          dataTable([
            { label: 'source', field: 'quoi', mono: true, raw: true },
            { label: 'quand', cell: function (r) { return fmtRel(r.quand); } },
            { label: 'horodatage', cell: function (r) { return el('span', { class: 'ts', text: fmtStamp(r.quand) }); } }
          ], rows, {})
        ])
      ]));

      var sch = st.schedule || {};
      if (sch.slots && sch.slots.length) {
        restHost.appendChild(el('div', { class: 'hr' }));
        restHost.appendChild(el('div', { class: 'stack' }, [
          el('div', { class: 'eyebrow', text: 'horaire OBSERVÉ dans les reçus — jamais configuré ici' }),
          dataTable([
            { label: 'créneau', field: 'slot', mono: true, raw: true },
            { label: 'heure locale', field: 'local_time', mono: true, raw: true },
            { label: 'passages', field: 'runs', num: true },
            { label: 'dernier', cell: function (r) { return fmtRel(r.last_run_at); } },
            { label: 'horodatage', cell: function (r) { return el('span', { class: 'ts', text: fmtStamp(r.last_run_at) }); } }
          ], sch.slots, {}),
          el('p', { class: 'tiny faint', text: (sch.note || '') + ' · source : ' + (sch.source || '—') })
        ]));
      }

      var t = st.tailer || {};
      restHost.appendChild(el('div', { class: 'hr' }));
      restHost.appendChild(el('div', { class: 'stack' }, [
        el('div', { class: 'eyebrow', text: 'le suiveur' }),
        el('dl', { class: 'kv' }, [
          el('dt', { text: 'en marche' }), el('dd', { text: t.running ? 'oui' : 'non' }),
          el('dt', { text: 'amorcé' }), el('dd', { text: t.bootstrapped ? 'oui' : 'non' }),
          el('dt', { text: 'passages' }), el('dd', { class: 'mono', text: fmtNum(t.passes) }),
          el('dt', { text: 'événements émis' }), el('dd', { class: 'mono', text: fmtNum(t.events_emitted) }),
          el('dt', { text: 'anneau' }), el('dd', { class: 'mono', text: fmtNum(t.ring_size) + ' / ' + fmtNum(t.ring_capacity) }),
          el('dt', { text: 'clients' }), el('dd', { class: 'mono', text: fmtNum(t.clients_connected) }),
          el('dt', { text: 'dégradé' }), el('dd', { text: t.degraded ? 'oui — ' + (t.last_error || '') : 'non' })
        ])
      ]));
    }
    host.appendChild(section('Le repos, et ce qui vient', null, restHost));

    /* transport : dire ce qu'on fait vraiment */
    var tr = S.transport;
    host.appendChild(section('Transport', null, tr ? el('div', { class: 'stack' }, [
      el('dl', { class: 'kv' }, [
        el('dt', { text: 'mode' }), el('dd', { class: 'mono', text: tr.mode || '—' }),
        el('dt', { text: 'intervalle' }), el('dd', { class: 'mono', text: fmtNum(tr.interval_ms) + ' ms' }),
        el('dt', { text: 'le moteur publie' }), el('dd', { text: tr.engine_publishes ? 'oui' : 'non' }),
        el('dt', { text: 'pourquoi' }), el('dd', { text: tr.why || '—' }),
        el('dt', { text: 'conséquence' }), el('dd', { text: tr.consequence || '—' })
      ]),
      el('p', { class: 'tiny faint', text: tr.note || '' })
    ]) : naBlock({ title: 'Transport inconnu', reason: 'le catalogue du flux n\'a pas répondu' })));

    /* croissance : ce que le cerveau a réellement gagné */
    var g = metricsOf('croissance');
    host.appendChild(section('Croissance', el('span', { class: 'tiny faint', text: plural(g.length, 'métrique') }),
      g.length ? metricGrid(g) : emptyBlock('Aucune métrique de croissance', 'le registre n\'en publie pas.')));
  }

  /* =======================================================================
     9 · DOMAINES GÉNÉRIQUES
     ======================================================================= */

  function domainSection(domain) {
    var list = metricsOf(domain);
    if (!list.length) {
      return emptyBlock('Aucune métrique dans le domaine « ' + domain +' »',
        'le registre n\'en publie aucune. Ce n\'est pas une page morte : c\'est un domaine que le cerveau ne mesure pas encore.');
    }
    return metricGrid(list);
  }

  function plural(n, word) { return n + ' ' + word + (n > 1 ? 's' : ''); }

  function viewDomain(host, domain, extra) {
    var list = metricsOf(domain);
    host.appendChild(section('Mesures',
      el('span', { class: 'tiny faint', text: list.length ? plural(list.length, 'métrique') + ' · un clic ouvre la preuve' : '' }),
      domainSection(domain)));
    if (extra) extra(host);
  }

  /* =======================================================================
     10 · CONVERSATIONS
     ======================================================================= */

  var CONV_ORDER = [
    ['content_date', 'date du contenu'], ['received_date', 'date de réception'],
    ['queue_rank', 'rang de file'], ['messages', 'messages'],
    ['atoms_generated', 'atomes produits'], ['curated_pct', 'moins curées d\'abord'],
    ['curated_at', 'date de curation'], ['status', 'statut'], ['title', 'titre']
  ];

  function viewConversations(host, q) {
    viewDomain(host, 'conversations');
    var listHost = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de la file…' }));
    host.appendChild(section('La file', el('span', { class: 'tiny faint', text: 'statut DÉRIVÉ en SQL du curseur de curation — aucun agent ne le tient à jour, donc aucun ne peut le laisser mentir' }), listHost));

    var params = {
      limit: q.limit || 50, offset: q.offset || 0, status: q.status || '',
      source: q.source || '', q: q.q || '', order: q.order || 'content_date'
    };
    get(API + '/conversations' + qs(params)).then(function (r) {
      clear(listHost);
      if (!r.ok) { listHost.appendChild(naBlock({ title: 'La file n\'a pas pu être lue', reason: r.reason })); return; }
      var d = r.data || {};
      var facets = d.facets || {};

      var tb = el('div', { class: 'toolbar' });
      tb.appendChild(searchField(q, 'q', 'chercher'));
      tb.appendChild(pillGroup(q, 'status', facets.by_status, 'tous statuts'));
      tb.appendChild(pillGroup(q, 'source', facets.by_source, 'toutes sources'));
      tb.appendChild(selectField(q, 'order', CONV_ORDER, 'tri'));
      var sqlBtn = registerSqlEvidence('conv', d.evidence);
      if (sqlBtn) tb.appendChild(sqlBtn);
      listHost.appendChild(tb);

      if (d.queue) {
        listHost.appendChild(el('p', { class: 'tiny faint', text: 'file : ' + fmtNum(d.queue.size) + ' — ' + d.queue.rule }));
      }

      listHost.appendChild(dataTable([
        { label: 'chaîne', cell: function (r2) { return chainMini(r2.chain); }, nowrap: true },
        { label: 'statut', cell: function (r2) { return stateChip(convState(r2.status), r2.status); }, nowrap: true },
        { label: 'conversation', cls: 't1', cell: function (r2) {
            return el('span', {}, [
              el('div', { text: r2.title || '(sans titre)' }),
              el('div', { class: 'card-key', text: r2.uid })
            ]);
          } },
        { label: 'source', field: 'source_type', mono: true, raw: true },
        { label: 'messages', field: 'messages', num: true },
        { label: 'atomes', field: 'atoms_generated', num: true },
        { label: 'curée', num: true, cell: function (r2) {
            return el('span', { class: 'stack', style: 'gap:2px' }, [
              el('span', { class: 'mono', text: r2.curated_pct === null ? '—' : fmtNum(r2.curated_pct) + ' %' }),
              bar(r2.curated_pct, r2.curated_pct === 100 ? 'ok' : 'warn')
            ]);
          } },
        { label: 'rang', field: 'queue_rank', num: true },
        { label: 'dernier message', nowrap: true, cell: function (r2) { return fmtRel(r2.content_date); } }
      ], d.items || [], {
        href: function (r2) { return '#/conversations/' + encodeURIComponent(r2.uid); },
        empty: ['Aucune conversation à cet emplacement',
          'la file en compte ' + fmtNum(d.total) + ' : soit le filtre ne retient rien, soit la page demandée est au-delà de la dernière.']
      }));

      listHost.appendChild(pager(q, d));
    });
  }

  /* Les 5 statuts servis par /cc/v1/conversations sont désormais TOUS explicites.
     `pending` tombait dans le repli — comme tomberait un 6e statut inconnu, qui
     serait alors peint en ambre : une alarme portée sur un état qu'on ne comprend
     pas. Le repli devient neutre. Aucune teinte ne change sur les données servies
     (pending reste ambre) ; seul un statut NOUVEAU se signalerait au lieu d'être
     jugé. Le mot affiché, lui, reste le statut brut du moteur. */
  function convState(s) {
    if (s === 'done') return 'ok';
    if (s === 'error') return 'critical';
    if (s === 'excluded') return 'unavailable';
    if (s === 'partial') return 'warn';
    if (s === 'pending') return 'warn';
    return 'unavailable';
  }

  function viewConversation(host, uid) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de la conversation…' }));
    host.appendChild(box);
    get(API + '/conversations/' + encodeURIComponent(uid)).then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Conversation illisible', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Conversation inconnue', reason: d.reason || 'aucune ligne', gesture: 'vérifier l\'identifiant' }));
        if (d.evidence) box.appendChild(sqlBlock('la requête qui n\'a rien trouvé', (d.evidence.sql || '')));
        return;
      }
      var h = d.header || {};
      box.appendChild(el('div', { class: 'crumbs' }, [
        el('a', { href: '#/conversations', text: 'conversations' }),
        el('span', { class: 'sep', text: '/' }),
        el('span', { class: 'mono', text: h.uid })
      ]));
      box.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title', text: h.title || '(sans titre)' }),
        el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
          stateChip(convState(h.status), h.status),
          el('span', { class: 'chip', text: h.source_type || '—' }),
          el('span', { class: 'chip', text: fmtNum(h.messages) + ' messages' }),
          el('span', { class: 'chip', text: fmtNum(h.atoms_generated) + ' atomes' }),
          /* `#/cascade/<uid>` — la seule vue qui montre un trajet réussi EN ENTIER —
             n'était atteignable par aucun lien : le routage avait été réparé, mais
             l'entrée jamais posée. Il fallait taper l'URL à la main. La fiche d'une
             conversation en est l'entrée naturelle : c'est d'ici qu'on veut savoir
             ce que le cycle en a fait. */
          el('button', { class: 'pill', type: 'button',
            'data-go': '#/cascade/' + encodeURIComponent(uid),
            title: 'le trajet de cette conversation dans le cycle, étape par étape',
            text: '→ son trajet dans le cycle' }),
          registerSqlEvidence('conv-' + uid, d.evidence)
        ])
      ]));

      box.appendChild(section('Sa chaîne', null, el('div', { class: 'stack' }, [
        chainFull(d.chain), el('div', { class: 'hr' }), chainLegend()
      ])));

      box.appendChild(section('Identité', null, el('dl', { class: 'kv' }, [
        el('dt', { text: 'uid' }), el('dd', { class: 'mono', text: h.uid || '—' }),
        el('dt', { text: 'nœud' }), el('dd', { class: 'mono', text: h.node_id || '—' }),
        el('dt', { text: 'curseur' }), el('dd', { class: 'mono', text: fmtNum(h.cursor_id) + ' / ' + fmtNum(h.max_message_id) }),
        el('dt', { text: 'curée à' }), el('dd', { class: 'mono', text: h.curated_pct === null ? '—' : fmtNum(h.curated_pct) + ' %' }),
        el('dt', { text: 'dernier message' }), el('dd', { text: fmtStamp(h.content_date) + ' · ' + fmtRel(h.content_date) }),
        el('dt', { text: 'reçue' }), el('dd', { text: fmtStamp(h.received_date) }),
        el('dt', { text: 'curée' }), el('dd', { text: h.curated_at ? fmtStamp(h.curated_at) : '—' }),
        el('dt', { text: 'erreur' }), el('dd', { class: h.error ? 'err' : '', text: h.error || '—' }),
        el('dt', { text: 'reprises' }), el('dd', { class: 'mono', text: fmtNum(h.retry_count) }),
        el('dt', { text: 'exclusion' }), el('dd', { text: h.exclusion_reason || '—' })
      ])));

      var atoms = (d.atoms_created || []).concat(d.atoms_enriched || []);
      box.appendChild(section('Ce qu\'elle a produit',
        el('span', { class: 'tiny faint', text: fmtNum(d.atoms_total) + ' atomes' + (d.atoms_truncated ? ' (tronqué)' : '') }),
        atoms.length ? dataTable([
          { label: 'kind', field: 'kind', mono: true, raw: true },
          { label: 'scope', field: 'scope', mono: true, raw: true },
          { label: 'clé', field: 'key', mono: true, raw: true, cls: 't1' },
          { label: 'statut', field: 'status', mono: true, raw: true },
          { label: 'confiance', field: 'confidence_score', num: true },
          { label: 'créé', cell: function (r2) { return fmtRel(r2.created_at); } }
        ], atoms, { href: function (r2) { return '#/atomes/' + encodeURIComponent(r2.id); } })
          : emptyBlock('Aucun atome produit', 'cette conversation n\'a pas encore livré de savoir — ce n\'est pas zéro atome de valeur, c\'est un travail non fait.')));

      if ((d.dropped || []).length) {
        box.appendChild(section('Ce qui a été écarté', null, dataTable([
          { label: 'raison', field: 'drop_reason', mono: true, raw: true },
          { label: 'scope', field: 'scope', mono: true, raw: true },
          { label: 'kind', field: 'kind', mono: true, raw: true },
          { label: 'statut', field: 'status', mono: true, raw: true },
          { label: 'quand', cell: function (r2) { return fmtRel(r2.created_at); } }
        ], d.dropped, {})));
      }

      if ((d.runs || []).length) {
        box.appendChild(section('Les passages qui l\'ont traitée', null, dataTable([
          { label: 'créneau', field: 'slot_key', mono: true, raw: true },
          { label: 'statut', cell: function (r2) { return stateChip(r2.status === 'done' ? 'ok' : r2.status === 'quarantined' ? 'critical' : 'warn', r2.status); } },
          { label: 'modèle', field: 'model', mono: true, raw: true },
          { label: 'items', field: 'items', num: true },
          { label: 'atomes', field: 'atoms_created', num: true },
          { label: 'quarantaine', field: 'atoms_quarantined', num: true },
          { label: 'arrêt', field: 'stop_reason', mono: true, raw: true },
          { label: 'début', cell: function (r2) { return fmtRel(r2.started_at); } }
        ], d.runs, {})));
      }

      var mp = d.messages_preview || {};
      box.appendChild(section('Ses messages', null, el('div', { class: 'stack' }, [
        el('dl', { class: 'kv' }, [
          el('dt', { text: 'nombre' }), el('dd', { class: 'mono', text: fmtNum(mp.count) }),
          el('dt', { text: 'premier' }), el('dd', { text: fmtStamp(mp.first_at) }),
          el('dt', { text: 'dernier' }), el('dd', { text: fmtStamp(mp.last_at) }),
          el('dt', { text: 'rôles' }), el('dd', { class: 'mono', text: mp.roles ? JSON.stringify(mp.roles) : '—' })
        ]),
        el('p', { class: 'tiny faint', text: mp.note || '' })
      ])));

      if (d.links && d.links.state === 'unavailable') {
        box.appendChild(section('Ses liens', null, naBlock({
          title: 'Maillon « Reliée » — organe non branché', reason: d.links.reason,
          gesture: d.links.gesture, substitute: d.links.substitute, source: 'arac.atom_links'
        })));
      }
    });
  }

  /* =======================================================================
     11 · ATOMES
     ======================================================================= */

  var ATOM_ORDER = [
    ['created_at', 'création'], ['updated_at', 'mise à jour'], ['usage_count', 'usage'],
    ['confidence_score', 'confiance'], ['last_served_at', 'dernier service'],
    ['key', 'clé'], ['scope', 'scope'], ['kind', 'kind']
  ];

  function viewAtomes(host, q) {
    /* Les vues comptées par le moteur, en onglets. C'est l'entrée principale
       de cet écran : chaque onglet est une question posée au cerveau, et sa
       réponse est un compte servi, jamais un compte de lignes reçues. */
    atomViewsSection(host, q);

    var listHost = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture des atomes…' }));
    host.appendChild(section('Le savoir', el('span', { class: 'tiny faint', text: 'extrait de 200 caractères découpé EN SQL — la valeur entière ne sort jamais de la liste' }), listHost));

    var params = {
      limit: q.limit || 50, offset: q.offset || 0, view: q.view || '', scope: q.scope || '',
      scope_prefix: q.scope_prefix || '', kind: q.kind || '', status: q.status || 'active',
      q: q.q || '', order: q.order || 'created_at'
    };
    get(API + '/atoms' + qs(params)).then(function (r) {
      clear(listHost);
      if (!r.ok) { listHost.appendChild(naBlock({ title: 'Les atomes n\'ont pas pu être lus', reason: r.reason })); return; }
      var d = r.data || {};
      var facets = d.facets || {};
      var view = d.view || {};

      var tb = el('div', { class: 'toolbar' });
      tb.appendChild(searchField(q, 'q', 'chercher dans la valeur'));
      if (view.available) {
        var vsel = view.available.map(function (v) { return [v, v]; });
        tb.appendChild(selectField(q, 'view', vsel, 'vue'));
      }
      tb.appendChild(selectField(q, 'kind', facetOptions(facets.by_kind), 'kind'));
      tb.appendChild(selectField(q, 'scope', facetOptions(facets.by_scope), 'scope'));
      tb.appendChild(selectField(q, 'status', [['active', 'actifs'], ['*', 'tous'], ['archived', 'archivés'],
        ['superseded', 'remplacés'], ['draft', 'brouillons'], ['low_confidence_archive', 'confiance basse']], 'statut'));
      tb.appendChild(selectField(q, 'order', ATOM_ORDER, 'tri'));
      var sqlBtn = registerSqlEvidence('atoms', d.evidence);
      if (sqlBtn) tb.appendChild(sqlBtn);
      listHost.appendChild(tb);

      if (view.label) listHost.appendChild(el('p', { class: 'tiny faint', text: 'vue « ' + view.key + ' » — ' + view.label }));

      listHost.appendChild(dataTable([
        { label: 'kind', field: 'kind', mono: true, raw: true, nowrap: true },
        { label: 'scope', mono: true, nowrap: true, cell: function (a) {
            return el('button', { class: 'pill', type: 'button', 'data-go': '#/scopes/' + encodeURIComponent(a.scope), text: a.scope });
          } },
        { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
        { label: 'extrait', wrap: true, cell: function (a) { return el('span', { class: 'small', text: cut(a.excerpt, 150) }); } },
        { label: 'conf.', field: 'confidence_score', num: true },
        { label: 'servi', num: true, cell: function (a) {
            return el('span', { class: 'mono', text: a.never_served ? '—' : fmtNum(a.usage_count) });
          } },
        { label: 'créé', nowrap: true, cell: function (a) { return fmtRel(a.created_at); } }
      ], d.items || [], {
        href: function (a) { return '#/atomes/' + encodeURIComponent(a.id); },
        empty: ['Aucun atome à cet emplacement',
          'la liste en compte ' + fmtNum(d.total) + ' : soit le filtre ne retient rien, soit la page demandée est au-delà de la dernière.']
      }));

      listHost.appendChild(pager(q, d));
    });
  }

  function facetOptions(obj) {
    var out = [];
    if (!obj) return out;
    var keys = Object.keys(obj);
    keys.sort(function (a, b) { return obj[b] - obj[a]; });
    for (var i = 0; i < keys.length; i++) out.push([keys[i], keys[i] + ' (' + fmtNum(obj[keys[i]]) + ')']);
    return out;
  }

  /* DEUX LECTURES DU MÊME ATOME, et de quoi passer de l'une à l'autre.
     CE QUI ÉTAIT FAUX : `viewAtome` — 109 lignes, la fiche complète servie par
     /cc/v1/atoms/{id} — n'était appelée nulle part. Le routeur envoyait
     `#/atomes/<id>` vers `viewAtomeStory` et rien d'autre : la vue était du code
     mort, et avec elle une route serveur que plus aucun écran ne consommait.
     CE QUE CETTE VERSION GARANTIT : `?vue=fiche` ouvre la fiche, sans paramètre on
     garde l'histoire (le comportement en place, donc aucun lien existant ne change).
     Les deux lectures s'annoncent l'une l'autre. */
  function atomeVueToggle(current) {
    var mk = function (val, label, why) {
      return el('button', {
        class: 'pill', type: 'button', title: why,
        'aria-pressed': current === val ? 'true' : 'false',
        text: label,
        onclick: function () { navPatch({ vue: val === 'histoire' ? '' : val }); }
      });
    };
    return el('div', { class: 'toolbar', style: 'gap:6px;margin:0' }, [
      mk('histoire', 'histoire', 'ce que cet atome est devenu : naissance, versions, usage dans le temps'),
      mk('fiche', 'fiche', 'l\'état courant servi par /cc/v1/atoms/{id} : identité, provenance, voisins, liens')
    ]);
  }

  function viewAtome(host, id) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de l\'atome…' }));
    host.appendChild(box);
    get(API + '/atoms/' + encodeURIComponent(id)).then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Atome illisible', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Atome inconnu', reason: d.reason || 'aucune ligne' }));
        return;
      }
      var i = d.identity || {}, c = d.content || {}, p = d.provenance || {};
      box.appendChild(el('div', { class: 'crumbs' }, [
        el('a', { href: '#/atomes', text: 'atomes' }), el('span', { class: 'sep', text: '/' }),
        el('a', { href: '#/scopes/' + encodeURIComponent(i.scope || ''), text: i.scope || '—' }),
        el('span', { class: 'sep', text: '/' }), el('span', { class: 'mono', text: cut(i.key, 60) })
      ]));
      box.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title mono', text: i.key || id }),
        el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
          stateChip(i.status === 'active' ? 'ok' : i.status === 'superseded' ? 'warn' : 'unavailable', i.status),
          el('span', { class: 'chip', text: i.kind || '—' }),
          el('span', { class: 'chip', text: 'v' + fmtNum(i.version) }),
          i.is_root_scoped ? el('span', { class: 'chip', 'data-state': 'warn' }, [glyph('warn'), el('span', { text: 'scope racine — invisible au rappel' })]) : null,
          atomeVueToggle('fiche'),
          registerSqlEvidence('atom-' + id, d.evidence)
        ])
      ]));

      box.appendChild(section('Ce qu\'il dit', null, el('div', { class: 'stack' }, [
        el('p', { class: 'excerpt', text: c.value || '—' }),
        c.rationale ? el('p', { class: 'excerpt tiny faint', text: c.rationale }) : null,
        (i.tags && i.tags.length) ? el('div', { class: 'tags' }, i.tags.map(function (t) { return el('span', { class: 'tag', text: t }); })) : null
      ])));

      box.appendChild(section('Identité', null, el('dl', { class: 'kv' }, [
        el('dt', { text: 'id' }), el('dd', { class: 'mono', text: i.id || '—' }),
        el('dt', { text: 'scope' }), el('dd', { class: 'mono', text: i.scope || '—' }),
        el('dt', { text: 'confiance' }), el('dd', { class: 'mono', text: (i.confidence || '—') + ' · ' + fmtNum(i.confidence_score) }),
        el('dt', { text: 'créé' }), el('dd', { text: fmtStamp(i.created_at) + ' · ' + fmtRel(i.created_at) }),
        el('dt', { text: 'mis à jour' }), el('dd', { text: fmtStamp(i.updated_at) }),
        el('dt', { text: 'vérifié' }), el('dd', { text: i.last_verified_at ? fmtStamp(i.last_verified_at) : '—' }),
        el('dt', { text: 'confirmé jusqu\'à' }), el('dd', { text: i.confirmed_until ? fmtStamp(i.confirmed_until) : '—' }),
        el('dt', { text: 'périmé' }), el('dd', { text: i.is_stale === null ? '—' : (i.is_stale ? 'oui' : 'non') }),
        el('dt', { text: 'plongement' }), el('dd', { text: i.has_embedding ? 'présent' : 'absent' })
      ])));

      box.appendChild(section('D\'où il vient', null, el('div', { class: 'stack' }, [
        p.conversation_uid ? el('button', {
          class: 'pill', type: 'button', 'data-go': '#/conversations/' + encodeURIComponent(p.conversation_uid),
          text: '→ ' + (p.conversation_title || p.conversation_uid)
        }) : el('p', { class: 'small muted', text: 'aucune conversation d\'origine résolvable' }),
        el('dl', { class: 'kv' }, [
          el('dt', { text: 'nœud' }), el('dd', { class: 'mono', text: p.node_id || '—' }),
          el('dt', { text: 'source' }), el('dd', { class: 'mono', text: p.conversation_source_type || '—' }),
          el('dt', { text: 'source_ref' }), el('dd', { class: 'mono tiny', text: p.source_ref ? JSON.stringify(p.source_ref) : '—' })
        ])
      ])));

      var lin = d.lineage || {};
      box.appendChild(section('Sa lignée', null,
        (lin.versions && lin.versions.length) ? dataTable([
          { label: 'version', field: 'version', num: true },
          { label: 'statut', field: 'status', mono: true, raw: true },
          { label: 'clé', field: 'key', mono: true, raw: true },
          { label: 'saut', field: 'hop', num: true },
          { label: 'créée', cell: function (v) { return fmtRel(v.created_at); } }
        ], lin.versions, { href: function (v) { return '#/atomes/' + encodeURIComponent(v.id); } })
          : emptyBlock('Aucune version antérieure', 'cet atome n\'a jamais été remplacé.')));

      var ns = d.neighbors_state || {};
      box.appendChild(section('Ses voisins sémantiques',
        el('span', { class: 'tiny faint', text: ns.operator || '' }),
        (d.neighbors && d.neighbors.length) ? dataTable([
          { label: 'distance', field: 'distance', num: true },
          { label: 'kind', field: 'kind', mono: true, raw: true },
          { label: 'scope', field: 'scope', mono: true, raw: true },
          { label: 'clé', field: 'key', mono: true, raw: true, cls: 't1' }
        ], d.neighbors, { href: function (n) { return '#/atomes/' + encodeURIComponent(n.id); } })
          : naBlock({ title: 'Voisinage indisponible', reason: ns.reason || 'aucun voisin' })));

      var u = d.usage || {};
      box.appendChild(section('Son usage réel', null, el('div', { class: 'stack' }, [
        el('dl', { class: 'kv' }, [
          el('dt', { text: 'servi' }), el('dd', { class: 'mono', text: u.never_served ? 'jamais' : fmtNum(u.served_count) + ' fois' }),
          el('dt', { text: 'dernier service' }), el('dd', { text: u.last_served_at ? fmtStamp(u.last_served_at) : '—' }),
          el('dt', { text: 'rang moyen' }), el('dd', { class: 'mono', text: u.avg_rank === null || u.avg_rank === undefined ? '—' : fmtNum(u.avg_rank) })
        ]),
        (u.queries && u.queries.length) ? dataTable([
          { label: 'consommateur', field: 'consumer', mono: true, raw: true },
          { label: 'bande', field: 'final_band', mono: true, raw: true },
          { label: 'arrêt', field: 'stop_reason', mono: true, raw: true },
          { label: 'quand', cell: function (x) { return fmtRel(x.created_at); } }
        ], u.queries, {}) : null
      ])));

      if (d.links && d.links.state === 'unavailable') {
        box.appendChild(section('Ses liens', null, naBlock({
          title: 'Maillon « Reliée » — organe non branché', reason: d.links.reason,
          gesture: d.links.gesture, substitute: d.links.substitute, source: 'arac.atom_links'
        })));
      }

      if (d.projects && d.projects.length) {
        box.appendChild(section('Ses projets', null, el('div', { class: 'toolbar' }, d.projects.map(function (pr) {
          return el('button', { class: 'pill', type: 'button', 'data-go': '#/projets/' + encodeURIComponent(pr.id), text: pr.label });
        }))));
      }
    });
  }

  /* =======================================================================
     12 · SCOPES · PROJETS · GRAPHES · OBSERVABILITÉ
     ======================================================================= */

  function viewMemoire(host) {
    viewDomain(host, 'memoire');
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture des territoires…' }));
    host.appendChild(section('Les territoires du savoir', el('span', { class: 'tiny faint', text: 'un atome posé sur une RACINE est invisible au rappel' }), box));
    get(API + '/scopes').then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Territoires illisibles', reason: r.reason })); return; }
      var d = r.data || {};
      var t = d.totals || {};
      box.appendChild(el('div', { class: 'toolbar' }, [
        el('span', { class: 'chip', text: fmtNum(t.scopes) + ' scopes' }),
        el('span', { class: 'chip', text: fmtNum(t.root_scopes) + ' racines' }),
        el('span', { class: 'chip', 'data-state': 'warn' }, [glyph('warn'), el('span', { text: fmtNum(t.root_level_debt) + ' atomes en dette root-level' })]),
        el('span', { class: 'chip', text: fmtNum(t.registry_scopes) + ' indexés par le routeur' }),
        registerSqlEvidence('scopes', d.evidence)
      ]));
      box.appendChild(dataTable([
        { label: 'chemin', cls: 't1', mono: true, raw: true, field: 'path' },
        { label: 'racine', cell: function (s) { return s.is_root ? stateChip('warn', 'racine') : el('span', { class: 'faint', text: '—' }); } },
        { label: 'atomes', field: 'atom_count', num: true },
        { label: 'dormants', num: true, cell: function (s) {
            return el('span', { class: 'stack', style: 'gap:2px' }, [
              el('span', { class: 'mono', text: fmtNum(s.dormant_count) + ' · ' + fmtNum(s.dormant_pct) + ' %' }),
              bar(s.dormant_pct, 'na')
            ]);
          } },
        { label: 'décisions', field: 'decisions', num: true },
        { label: 'pièges', field: 'gotchas', num: true },
        { label: 'kinds', field: 'kinds', num: true },
        { label: 'dernier atome', nowrap: true, cell: function (s) { return fmtRel(s.last_atom_at); } }
      ], d.items || [], { href: function (s) { return '#/scopes/' + encodeURIComponent(s.path); } }));
      box.appendChild(el('p', { class: 'tiny faint', text: d.note || '' }));
    });
  }

  function viewProjets(host) {
    viewDomain(host, 'projets');
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture des projets…' }));
    host.appendChild(section('Les projets', el('span', { class: 'tiny faint', text: 'un projet est une RÈGLE de sélection, pas un dossier' }), box));
    get(API + '/projects').then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Projets illisibles', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.decision) box.appendChild(el('p', { class: 'tiny faint', text: d.decision }));
      var btn = registerSqlEvidence('projects', d.evidence);
      if (btn) box.appendChild(el('div', { class: 'toolbar' }, btn));
      box.appendChild(dataTable([
        { label: 'projet', cls: 't1', field: 'label', raw: true },
        { label: 'état', cell: function (p) {
            return stateChip(p.state === 'actif' ? 'ok' : p.state === 'bloqué' ? 'critical' : p.state === 'vide' ? 'unavailable' : 'warn', p.state);
          } },
        { label: 'atomes', field: 'atom_count', num: true },
        { label: 'décisions', field: 'decisions', num: true },
        { label: 'pièges', field: 'gotchas', num: true },
        { label: 'dormants', num: true, cell: function (p) {
            return el('span', { class: 'mono', text: fmtNum(p.dormant_count) + ' · ' + fmtNum(p.dormant_pct) + ' %' });
          } },
        { label: 'conversations', field: 'conversation_count', num: true },
        { label: 'en attente', field: 'conversations_waiting', num: true },
        { label: 'dernière activité', nowrap: true, cell: function (p) { return fmtRel(p.last_activity); } }
      ], d.items || [], { href: function (p) { return '#/projets/' + encodeURIComponent(p.id); } }));
      if (d.states_legend) {
        var rows = [];
        for (var k in d.states_legend) {
          if (!Object.prototype.hasOwnProperty.call(d.states_legend, k)) continue;
          rows.push(el('dt', { text: k }), el('dd', { text: d.states_legend[k] }));
        }
        box.appendChild(el('dl', { class: 'kv tiny', style: 'margin-top:16px' }, rows));
      }
    });
  }

  function viewProjet(host, id) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture du projet…' }));
    host.appendChild(box);
    get(API + '/projects/' + encodeURIComponent(id)).then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Projet illisible', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') { box.appendChild(naBlock({ title: 'Projet inconnu', reason: d.reason })); return; }
      var h = d.header || {};
      box.appendChild(el('div', { class: 'crumbs' }, [
        el('a', { href: '#/projets', text: 'projets' }), el('span', { class: 'sep', text: '/' }),
        el('span', { class: 'mono', text: h.id })
      ]));
      box.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title', text: h.label || id }),
        el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
          stateChip(h.state === 'actif' ? 'ok' : h.state === 'bloqué' ? 'critical' : h.state === 'vide' ? 'unavailable' : 'warn', h.state),
          el('span', { class: 'chip', text: fmtNum(h.atom_count) + ' atomes' }),
          el('span', { class: 'chip', text: fmtNum(h.decisions) + ' décisions' }),
          el('span', { class: 'chip', text: fmtNum(h.gotchas) + ' pièges' }),
          registerSqlEvidence('project-' + id, d.evidence)
        ]),
        h.rule ? el('p', { class: 'view-sub tiny mono', text: 'règle : scopes ' + JSON.stringify(h.rule.scopes || []) + (h.rule.keywords && h.rule.keywords.length ? ' · mots-clés ' + JSON.stringify(h.rule.keywords) : '') + ' · ' + (h.rule.combination || '') }) : null
      ]));

      /* Le graphe vivant du projet — servi par /cc/v1/projects/{id}/graph. */
      projectGraphSection(box, id);

      // Le compte affiché est celui que le MOTEUR sert (d.blocks[kind].total),
      // jamais rows.length : le SQL borne la liste par nature, donc compter les
      // lignes reçues afficherait un chiffre du cerveau produit par le navigateur,
      // et faux dès qu'un projet dépasse la borne. Quand la liste est tronquée,
      // on le dit — un total sans mention de troncature laisserait croire à une
      // liste complète.
      var blocks = [['decisions', 'decision', 'Décisions'], ['gotchas', 'gotcha', 'Pièges'],
                    ['states', 'state', 'États'], ['references', 'reference', 'Références']];
      blocks.forEach(function (b) {
        var rows = d[b[0]] || [];
        var meta = (d.blocks || {})[b[1]] || {};
        var total = (typeof meta.total === 'number') ? meta.total : null;
        box.appendChild(section(b[2], el('span', {
            class: 'tiny faint',
            text: total === null ? '—' : fmtNum(total) + (meta.truncated ? ' · ' + fmtNum(meta.shown) + ' affichés' : ''),
            title: total === null ? 'total non servi par le moteur' : 'total servi par le moteur'
          }),
          rows.length ? dataTable([
            { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
            { label: 'scope', field: 'scope', mono: true, raw: true },
            { label: 'extrait', wrap: true, cell: function (x) { return el('span', { class: 'small', text: cut(x.excerpt, 160) }); } },
            { label: 'conf.', field: 'confidence_score', num: true },
            { label: 'créé', nowrap: true, cell: function (x) { return fmtRel(x.created_at); } }
          ], rows, { href: function (x) { return '#/atomes/' + encodeURIComponent(x.id); } })
            : emptyBlock('Aucun élément', 'la règle de ce projet ne sélectionne rien de ce type.')));
      });

      if ((d.scopes_breakdown || []).length) {
        box.appendChild(section('Ses territoires', null, dataTable([
          { label: 'scope', cls: 't1', mono: true, raw: true, field: 'scope' },
          { label: 'atomes', field: 'atom_count', num: true },
          { label: 'dormants', num: true, cell: function (s) { return el('span', { class: 'mono', text: fmtNum(s.dormant_count) + ' · ' + fmtNum(s.dormant_pct) + ' %' }); } },
          { label: 'dernier atome', nowrap: true, cell: function (s) { return fmtRel(s.last_atom_at); } }
        ], d.scopes_breakdown, { href: function (s) { return '#/scopes/' + encodeURIComponent(s.scope); } })));
      }

      if ((d.conversations || []).length) {
        box.appendChild(section('Ses conversations', null, dataTable([
          { label: 'titre', cls: 't1', raw: true, field: 'title' },
          { label: 'statut', cell: function (c) { return stateChip(convState(c.status), c.status); } },
          { label: 'atomes ici', field: 'atoms_here', num: true },
          { label: 'atomes produits', field: 'atoms_generated', num: true },
          { label: 'curée', nowrap: true, cell: function (c) { return fmtRel(c.curated_at); } }
        ], d.conversations, { href: function (c) { return '#/conversations/' + encodeURIComponent(c.uid); } })));
      }

      if ((d.timeline || []).length) {
        box.appendChild(section('Sa chronologie', null, dataTable([
          { label: 'quand', nowrap: true, cell: function (t) { return fmtRel(t.at); } },
          { label: 'horodatage', nowrap: true, cell: function (t) { return el('span', { class: 'ts', text: fmtStamp(t.at) }); } },
          { label: 'type', field: 'type', mono: true, raw: true },
          { label: 'quoi', wrap: true, field: 'label', raw: true }
        ], d.timeline, {})));
      }

      if (d.links && d.links.state === 'unavailable') {
        box.appendChild(section('Son sous-graphe', null, naBlock({
          title: 'Indisponible', reason: d.links.reason, gesture: d.links.gesture,
          substitute: d.links.substitute, impact: d.links.impact
        })));
      }
    });
  }

  function viewGraphes(host) {
    var dep = null;
    if (S.status && S.status.dependencies) dep = S.status.dependencies.atom_links;
    host.appendChild(section('L\'étage graphes', null, el('div', { class: 'stack' }, [
      el('p', { class: 'lede', text: 'Cinquième maillon de la chaîne : relier les atomes entre eux. Il n\'est pas cassé — il n\'est pas encore branché. Le cockpit le montre tel quel : ni vert, ni rouge.' }),
      dep ? naBlock({
        title: 'arac.atom_links — ' + dep.state, reason: dep.reason, gesture: dep.gesture,
        substitute: dep.substitute, impact: dep.impact, source: 'arac.atom_links'
      }) : naBlock({ title: 'Dépendance inconnue', reason: 'la route /cc/v1/status n\'a pas répondu' })
    ])));

    var m = metric('pipeline_graph_stage_installed');
    host.appendChild(section('Ce que le moteur en mesure', null,
      m ? metricGrid([m]) : emptyBlock('Aucune mesure', 'le registre ne publie rien sur cet étage.')));

    var list = metricsOf('graphes');
    if (list.length) host.appendChild(section('Domaine « graphes »', null, metricGrid(list)));
  }

  function viewObservabilite(host) {
    viewDomain(host, 'observabilite');

    /* Le cockpit vu par lui-même — ce qui est chargé, ce qui manque. */
    var st = S.status;
    var box = el('div', { class: 'stack' });
    if (!st) {
      box.appendChild(naBlock({ title: 'Auto-diagnostic indisponible', reason: '/cc/v1/status n\'a pas répondu' }));
    } else {
      var mt = st.metrics || {}, sm = st.submodules || {};
      box.appendChild(el('dl', { class: 'kv' }, [
        el('dt', { text: 'métriques' }), el('dd', { class: 'mono', text: fmtNum(mt.count) + ' (dont socle ' + fmtNum(mt.core) + ')' }),
        el('dt', { text: 'familles' }), el('dd', { class: 'mono', text: (mt.families || []).join(' · ') || '—' }),
        el('dt', { text: 'domaines' }), el('dd', { class: 'mono', text: (mt.domains || []).join(' · ') || '—' }),
        el('dt', { text: 'sous-modules' }), el('dd', { class: 'mono', text: (sm.loaded || []).join(' · ') || '—' }),
        el('dt', { text: 'attendus' }), el('dd', { class: 'mono', text: (sm.expected || []).join(' · ') || '—' })
      ]));
      var errs = [];
      var le = mt.load_errors || {};
      for (var k in le) { if (Object.prototype.hasOwnProperty.call(le, k)) errs.push({ quoi: k, err: le[k] }); }
      var se = sm.errors || {};
      for (var k2 in se) { if (Object.prototype.hasOwnProperty.call(se, k2)) errs.push({ quoi: k2, err: se[k2] }); }
      box.appendChild(errs.length
        ? dataTable([{ label: 'organe', field: 'quoi', mono: true, raw: true }, { label: 'erreur', field: 'err', wrap: true, raw: true }], errs, {})
        : el('p', { class: 'small muted', text: 'Aucune erreur de chargement rapportée par l\'API.' }));
    }
    host.appendChild(section('Le cockpit vu par lui-même', null, box));

    /* Les seuils déclarés, et l'état que l'API renvoie pour chacun.
       On n'évalue rien ici : on met la valeur, l'état servi et le seuil
       côte à côte, et on laisse voir. */
    var withTarget = [];
    if (S.metrics) S.metrics.forEach(function (m) { if (m.target) withTarget.push(m); });
    host.appendChild(section('Seuils déclarés',
      el('span', { class: 'tiny faint', text: plural(withTarget.length, 'métrique') + ' à seuil' }),
      el('div', { class: 'stack' }, [
        el('p', { class: 'tiny faint', text: 'Le cockpit n\'évalue AUCUN seuil : il affiche l\'état que /cc/v1/metrics renvoie, à côté de la cible que le registre déclare. Si les deux ne s\'accordent pas, la divergence est visible ici plutôt que masquée par une couleur choisie côté client.' }),
        withTarget.length ? dataTable([
          { label: 'métrique', cls: 't1', mono: true, raw: true, field: 'key' },
          { label: 'valeur', num: true, cell: function (m) { return el('span', { class: 'mono' }, [el('span', { text: metricValueText(m) }), el('span', { class: 'unit', text: m.unit || '' })]); } },
          { label: 'état servi', cell: function (m) { return stateChip(m.state, m.state); } },
          { label: 'cible déclarée', wrap: true, cell: function (m) { return el('span', { class: 'small', text: targetText(m.target) || '—' }); } },
          { label: 'preuve', cell: function (m) { return el('button', { class: 'pill', type: 'button', 'data-metric': m.key, text: '↗' }); } }
        ], withTarget, {}) : emptyBlock('Aucune cible déclarée', 'aucune métrique ne porte de seuil.')
      ])));
  }

  /* =======================================================================
     12bis · V2 — LE CERVEAU RACONTE SA VIE
     -----------------------------------------------------------------------
     Les écrans V1 disent des ÉTATS. Ceux-ci disent une VIE : ce que le cerveau
     a appris, retenu, remplacé, oublié, ou ne sait pas mesurer.

     Les trois règles du fichier tiennent ici aussi, et une quatrième s'ajoute :

     4. Aucune PHRASE de synthèse n'est écrite ici. « Aujourd'hui » compose ses
        phrases à partir des gabarits servis par /cc/v1/today/narrative — clé de
        gabarit + arguments + sources. Une clé inconnue rend le gabarit de repli
        servi par le moteur (`unknown_template`), jamais un texte deviné.

     CE QUE LE CODE A LE DROIT DE CALCULER ICI : des PIXELS. Une abscisse, un
     rayon, une hauteur de barre. Aucune de ces valeurs n'est affichée comme un
     chiffre, aucune ne rentre en base, aucune ne prétend mesurer le cerveau.
     Le moteur sert des poids et des comptes ; la géométrie n'est que du rendu.
     ======================================================================= */

  function hasOwn(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  /* ---- SVG sans espace de noms écrit en dur -------------------------------
     Un `createElementNS` demande l'URL de l'espace de noms SVG. L'écrire en
     toutes lettres ferait entrer une URL dans un fichier qui doit n'en contenir
     aucune (le cockpit marche hors ligne, et son contrôle d'autonomie le
     vérifie). On laisse donc l'analyseur HTML fabriquer la racine à partir d'un
     littéral statique SANS DONNÉE, puis on lit `namespaceURI` sur le nœud
     obtenu : le navigateur nous donne l'espace de noms, on ne le récite pas. */

  function svgBox(viewBox, cls, label, stretch) {
    var holder = document.createElement('div');
    holder.innerHTML = '<svg></svg>';
    var root = holder.firstChild;
    root.setAttribute('viewBox', viewBox);
    root.setAttribute('class', cls || '');
    root.setAttribute('role', 'img');
    if (label) root.setAttribute('aria-label', label);
    if (stretch) root.setAttribute('preserveAspectRatio', 'none');
    return root;
  }

  function sv(root, tag, attrs, text) {
    var n = document.createElementNS(root.namespaceURI, tag);
    if (attrs) {
      for (var k in attrs) {
        if (!hasOwn(attrs, k)) continue;
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
        else n.setAttribute(k, String(v));
      }
    }
    if (text !== null && text !== undefined) n.textContent = String(text);
    return n;
  }

  function svTitle(root, node, text) {
    if (text === null || text === undefined) return node;
    node.appendChild(sv(root, 'title', null, text));
    return node;
  }

  /* ---- une SOURCE servie : {kind, ref, label, href} ----------------------
     Le moteur désigne la source ; le cockpit sait ouvrir les genres qu'il
     connaît. Un genre inconnu n'est PAS deviné : on montre son étiquette et le
     chemin d'API servi, sans fabriquer un lien qui mènerait nulle part. */

  function sourceNode(src) {
    if (!src) return null;
    var label = src.label || src.ref || 'source';
    if (src.kind === 'metric') {
      return el('button', { class: 'pill', type: 'button', 'data-metric': src.ref,
        title: 'ouvrir la preuve de ' + src.ref, text: '↗ ' + label });
    }
    var hash = null;
    if (src.kind === 'project') hash = '#/projets/' + encodeURIComponent(src.ref);
    else if (src.kind === 'scope') hash = '#/scopes/' + src.ref;
    else if (src.kind === 'atom') hash = '#/atomes/' + encodeURIComponent(src.ref);
    else if (src.kind === 'conversation') hash = '#/conversations/' + encodeURIComponent(src.ref);
    if (hash) return el('button', { class: 'pill', type: 'button', 'data-go': hash, text: '→ ' + label });
    return el('span', { class: 'chip', 'data-state': 'unavailable', title: src.href || '' }, [
      glyph('unavailable'),
      el('span', { text: label }),
      el('span', { class: 'card-key', text: 'genre « ' + (src.kind || '?') + ' » sans écran dédié' })
    ]);
  }

  /* ---- composition d'une phrase : gabarit + arguments, rien d'autre ------ */

  function composeSentence(sen, templates, unknownTpl) {
    var tpl = (templates && sen && hasOwn(templates, sen.template_key)) ? templates[sen.template_key] : null;
    if (typeof tpl !== 'string') {
      var fallback = unknownTpl || '[phrase inconnue : {key}]';
      return { text: fallback.replace(/\{key\}/g, (sen && sen.template_key) || '?'), unknown: true };
    }
    var args = (sen && sen.args) || {};
    var out = tpl.replace(/\{(\w+)\}/g, function (whole, name) {
      if (!hasOwn(args, name)) return whole;
      var v = args[name];
      if (v === null || v === undefined) return '—';
      return typeof v === 'number' ? fmtNum(v) : String(v);
    });
    return { text: out, unknown: false };
  }

  function narrativeBlock(nar) {
    var sentences = (nar && nar.sentences) || [];
    var templates = (nar && nar.templates) || null;
    var unknownTpl = (nar && nar.unknown_template) || null;
    if (!sentences.length) {
      return emptyBlock('Le cerveau ne dit rien de cette fenêtre',
        'le moteur n\'a retenu aucun gabarit : il n\'y a rien à raconter, et rien n\'est écrit ici pour combler ce silence.');
    }
    var wrap = el('div', { class: 'narrative' });
    sentences.forEach(function (sen) {
      var c = composeSentence(sen, templates, unknownTpl);
      var srcs = sen.sources || [];
      var srcHost = el('div', { class: 'narr-sources' });
      srcHost.hidden = true;
      srcHost.appendChild(el('div', { class: 'tiny faint', text: sen.rule ? 'règle qui a déclenché cette phrase : ' + sen.rule : 'aucune règle servie pour cette phrase' }));
      srcHost.appendChild(el('div', { class: 'toolbar' }, srcs.length
        ? srcs.map(sourceNode)
        : el('span', { class: 'tiny faint', text: 'aucune source servie — la phrase reste invérifiable' })));
      var line = el('button', {
        class: 'narr q', type: 'button', 'data-unknown': c.unknown ? '1' : '0', 'aria-expanded': 'false',
        title: 'gabarit servi : ' + (sen.template_key || '?') + (sen.rule ? '\n\nrègle : ' + sen.rule : '') + '\n\nun clic montre ses sources'
      }, [
        el('span', { class: 'narr-mark', 'aria-hidden': 'true' }),
        el('span', { class: 'narr-text', text: c.text })
      ]);
      line.addEventListener('click', function () {
        var open = srcHost.hidden;
        srcHost.hidden = !open;
        line.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      wrap.appendChild(el('div', { class: 'narr-row' }, [line, srcHost]));
    });
    return wrap;
  }

  /* ---- les lignes de preuve d'une métrique, rendues telles qu'elles viennent
     Une preuve d'indisponibilité porte ses propres colonnes (`raison`, `geste`,
     `substitut`) : on les remonte dans le bloc d'absence au lieu de les noyer
     dans un tableau — une absence doit se lire, pas se déchiffrer. */

  function naFromEvidence(d, title) {
    var cols = d.columns || [], rows = d.rows || [];
    var ix = {}, i;
    for (i = 0; i < cols.length; i++) ix[cols[i]] = i;
    var r0 = rows.length ? rows[0] : null;
    function pick(name) { return (r0 && ix[name] !== undefined) ? r0[ix[name]] : null; }
    return naBlock({
      title: title || 'Mesure indisponible',
      reason: d.reason || pick('raison') || 'raison non servie',
      gesture: pick('geste'),
      substitute: pick('substitut'),
      source: pick('dependance') || pick('colonne') || pick('source')
    });
  }

  function evidenceRowsTable(d) {
    var cols = d.columns || [], rows = d.rows || [];
    var ix = {}, i;
    for (i = 0; i < cols.length; i++) ix[cols[i]] = i;
    var defs = cols.map(function (c, k) {
      return { label: c, mono: (c === 'id' || c === 'key' || c === 'scope' || c === 'kind'),
        wrap: (c === 'extrait' || c === 'histoire' || c === 'raison'),
        cell: function (row) { return row[k]; } };
    });
    var opts = {};
    var idCol = (ix.id !== undefined) ? ix.id : (ix.atome_id !== undefined ? ix.atome_id : null);
    if (idCol !== null) opts.href = function (row) { return '#/atomes/' + encodeURIComponent(row[idCol]); };
    else if (ix.scope !== undefined) opts.href = function (row) { return '#/scopes/' + row[ix.scope]; };
    else if (ix.projet !== undefined) opts.href = null;
    if (opts.href === null) delete opts.href;
    return dataTable(defs, rows, opts);
  }

  /* Une section bâtie sur LA PREUVE d'une métrique : le compte vient du
     registre, les lignes viennent du SQL de preuve. Le client n'en dérive rien. */
  function evidenceSection(host, key, opts) {
    opts = opts || {};
    var m = metric(key);
    var body = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture des lignes sources…' }));
    var right = m ? el('button', {
      class: 'pill', type: 'button', 'data-metric': key,
      title: m.definition + '\n\nun clic ouvre la preuve complète',
      text: (m.state === 'unavailable' ? '◇ ' : '') + metricValueText(m) + ' ' + (m.unit || '') + ' ↗'
    }) : el('span', { class: 'tiny faint', text: 'clé absente du registre' });
    host.appendChild(section(opts.title || (m ? m.label : key), right, body));
    get(API + '/evidence/' + encodeURIComponent(key) + '?limit=' + (opts.limit || 60)).then(function (r) {
      clear(body);
      if (m && m.definition) body.appendChild(el('p', { class: 'small muted', text: m.definition }));
      if (!r.ok) { body.appendChild(naBlock({ title: 'Lignes sources illisibles', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable' || (m && m.state === 'unavailable')) {
        body.appendChild(naFromEvidence(
          { columns: d.columns, rows: d.rows, reason: (m && m.reason) || d.reason },
          opts.naTitle || 'Mesure non alimentée'));
        if (m && m.detail) body.appendChild(el('p', { class: 'tiny faint', text: m.detail }));
        if ((d.rows || []).length) {
          body.appendChild(el('div', { class: 'eyebrow', text: 'ce que la base répond, constaté maintenant' }));
          body.appendChild(evidenceRowsTable(d));
        }
        return;
      }
      if ((d.rows || []).length) {
        body.appendChild(el('div', { class: 'eyebrow', text: d.evidence_label || 'lignes sources' }));
        body.appendChild(evidenceRowsTable(d));
        if (d.truncated) body.appendChild(el('p', { class: 'tiny faint', text: 'liste tronquée par la requête de preuve — le compte affiché reste celui du moteur.' }));
      } else {
        body.appendChild(emptyBlock('Aucune ligne source',
          'la requête de preuve n\'a rien retourné : c\'est une absence de lignes, pas un zéro mesuré.'));
      }
    });
  }

  /* =======================================================================
     12ter · « AUJOURD'HUI » — la page d'accueil du cerveau vivant
     ======================================================================= */

  function windowPicker(q, current, windows) {
    var wrap = el('div', { class: 'toolbar' });
    wrap.appendChild(el('span', { class: 'eyebrow', text: 'fenêtre' }));
    (windows || []).forEach(function (w) {
      var b = el('button', { class: 'pill', type: 'button', text: w,
        'aria-pressed': String(current) === String(w) ? 'true' : 'false' });
      b.addEventListener('click', function () { navPatch({ window: w }); });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function deltaCard(d) {
    var st = d.state || 'unavailable';
    var na = (st === 'unavailable') || (d.measurable === false);
    var ref = (d.evidence && d.evidence.ref) || d.key;
    var value = na
      ? el('div', { class: 'delta-value' }, el('span', { class: 'delta-na', text: 'non mesuré' }))
      : el('div', { class: 'delta-value' }, [
          el('span', { text: (d.value === null || d.value === undefined) ? '—' : fmtNum(d.value) }),
          d.unit ? el('span', { class: 'unit', text: d.unit }) : null
        ]);
    /* `data-window` : la carte affiche un chiffre de fenêtre (24h, 7d, 30d). Sans
       cet attribut, le tiroir ouvrait la preuve à 24 h codée en dur sous un chiffre
       à 30 jours. Il porte donc la fenêtre servie AVEC la clé — voir
       `openMetricEvidence(key, win)`. */
    return el('button', {
      class: 'delta q', type: 'button', 'data-state': st, 'data-na': na ? '1' : '0', 'data-metric': ref,
      'data-window': d.window || null,
      title: (d.definition || '') + (d.formula ? '\n\nformule : ' + d.formula : '') +
             (targetText(d.target) ? '\n' + targetText(d.target) : '') +
             '\n\nfenêtre : ' + (d.window || '—') + '\n\nun clic ouvre le chemin de preuve',
      'aria-label': (d.label || d.key) + ' — ouvrir la preuve'
    }, [
      el('div', { class: 'delta-label', text: d.label || d.key }),
      value,
      d.detail ? el('div', { class: 'delta-detail', text: d.detail }) : null,
      (na && d.reason) ? el('div', { class: 'delta-why', text: d.reason }) : null,
      el('div', { class: 'delta-foot' }, [
        glyph(st),
        el('span', { class: 'card-key', text: d.key }),
        el('span', { class: 'evidence-cue', text: na ? '↗ le constat' : '↗ preuve' })
      ])
    ]);
  }

  function highlightBlock(title, note, rows, cols, href, emptyWhy) {
    return section(title, note ? el('span', { class: 'tiny faint', text: note }) : null,
      (rows && rows.length) ? dataTable(cols, rows, href ? { href: href } : {})
        : emptyBlock('Rien sur cette fenêtre', emptyWhy));
  }

  function viewAujourdhui(host, q) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de la journée du cerveau…' }));
    host.appendChild(box);
    var w = q.window || '';

    Promise.all([
      get(API + '/today' + qs({ window: w })),
      get(API + '/today/narrative' + qs({ window: w }))
    ]).then(function (rs) {
      var rToday = rs[0], rNarr = rs[1];
      clear(box);
      if (!rToday.ok) {
        box.appendChild(naBlock({
          title: 'La journée du cerveau n\'a pas pu être lue', reason: rToday.reason,
          gesture: 'vérifier la session du Control Center et l\'accès PostgreSQL en lecture seule',
          substitute: 'l\'écran « État général » reste servi par le registre des métriques'
        }));
        return;
      }
      var d = rToday.data || {};

      box.appendChild(el('div', { class: 'toolbar' }, [
        windowPicker(q, d.window, d.windows),
        el('span', { class: 'tiny faint mono', text: fmtStamp(d.since) + ' → ' + fmtStamp(d.until) }),
        registerSqlEvidence('today', d.evidence)
      ]));

      /* --- 1 · LA SYNTHÈSE : des gabarits servis, jamais une phrase d'ici --- */
      var nar = rNarr.ok ? (rNarr.data || {}) : (d.narrative || {});
      var narHost = el('div', { class: 'stack' });
      if (!rNarr.ok && !d.narrative) {
        narHost.appendChild(naBlock({ title: 'Synthèse indisponible', reason: rNarr.reason,
          substitute: 'les deltas et les faits saillants restent servis ci-dessous' }));
      } else {
        narHost.appendChild(narrativeBlock(nar));
        if ((nar.refused_without_source || []).length) {
          narHost.appendChild(el('p', { class: 'tiny faint', text: 'phrases refusées faute de source : ' + nar.refused_without_source.join(' · ') }));
        }
        if (nar.doctrine) narHost.appendChild(el('p', { class: 'tiny faint', text: nar.doctrine }));
      }
      box.appendChild(section('Ce que le cerveau dit de lui-même',
        el('span', { class: 'tiny faint', text: 'un clic sur une phrase ouvre ses sources' }), narHost));

      /* --- 2 · LES DELTAS, en grand, chacun avec son chemin de preuve --- */
      var deltas = d.deltas || [];
      box.appendChild(section('Ce qui a bougé sur ' + (d.window_label || d.window || 'la fenêtre'),
        el('span', { class: 'tiny faint', text: 'une mesure absente n\'est jamais un zéro : elle porte sa raison' }),
        deltas.length ? el('div', { class: 'deltas' }, deltas.map(deltaCard))
          : emptyBlock('Aucun delta servi', 'le moteur n\'a publié aucune mesure de fenêtre.')));

      /* --- 3 · LES FAITS SAILLANTS --- */
      var h = d.highlights || {};

      box.appendChild(highlightBlock('Les nouveaux souvenirs', 'ce que le cerveau vient d\'apprendre',
        h.new_atoms, [
          { label: 'nature', field: 'kind', mono: true, raw: true, nowrap: true },
          { label: 'territoire', mono: true, nowrap: true, cell: function (a) {
              return el('span', {}, [
                el('span', { text: a.scope }),
                a.pose_sur_une_racine ? el('span', { class: 'chip', 'data-state': 'warn' },
                  [glyph('warn'), el('span', { text: 'racine' })]) : null
              ]);
            } },
          { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
          { label: 'ce qu\'il dit', wrap: true, cell: function (a) { return el('span', { class: 'small', text: cut(a.extrait, 170) }); } },
          { label: 'conf.', field: 'confidence_score', num: true },
          { label: 'né', nowrap: true, cell: function (a) { return fmtRel(a.created_at); } }
        ], function (a) { return '#/atomes/' + encodeURIComponent(a.id); },
        'aucun atome n\'est né sur cette fenêtre.'));

      box.appendChild(highlightBlock('Ce qui a été réécrit', 'le cerveau a affiné plutôt qu\'ajouté',
        h.enriched_atoms, [
          { label: 'nature', field: 'kind', mono: true, raw: true },
          { label: 'territoire', field: 'scope', mono: true, raw: true },
          { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
          { label: 'version', field: 'version', num: true },
          { label: 'réécrit', nowrap: true, cell: function (a) { return fmtRel(a.updated_at); } }
        ], function (a) { return '#/atomes/' + encodeURIComponent(a.id); },
        'aucun souvenir existant n\'a été retouché sur cette fenêtre.'));

      box.appendChild(highlightBlock('Les projets qui progressent', 'un atome peut appartenir à plusieurs projets : ces lignes ne s\'additionnent pas',
        h.progressed_projects, [
          { label: 'projet', cls: 't1', field: 'label', raw: true },
          { label: 'atomes gagnés', field: 'atomes_gagnes', num: true },
          { label: 'enrichis', field: 'atomes_enrichis', num: true },
          { label: 'atomes actifs', field: 'atomes_actifs', num: true },
          { label: 'dernier atome', nowrap: true, cell: function (p) { return fmtRel(p.dernier_atome); } }
        ], function (p) { return '#/projets/' + encodeURIComponent(p.project_id); },
        'aucun projet n\'a gagné d\'atome sur cette fenêtre.'));

      box.appendChild(highlightBlock('Les territoires touchés', 'un atome posé sur une RACINE reste invisible au rappel',
        h.touched_scopes, [
          { label: 'territoire', cls: 't1', mono: true, nowrap: true, cell: function (s) {
              return el('span', {}, [
                el('span', { text: s.scope }),
                s.scope_racine ? el('span', { class: 'chip', 'data-state': 'warn' },
                  [glyph('warn'), el('span', { text: 'racine — invisible au rappel' })]) : null
              ]);
            } },
          { label: 'créés', field: 'atomes_crees', num: true },
          { label: 'enrichis', field: 'atomes_enrichis', num: true },
          { label: 'atomes actifs', field: 'atomes_actifs', num: true }
        ], function (s) { return '#/scopes/' + s.scope; },
        'aucun territoire n\'a bougé sur cette fenêtre.'));

      /* /cc/v1/today sert SEPT blocs de faits saillants ; cet écran n'en rendait
         que six. `highlights.root_debt` — les territoires RACINES qui ont gagné des
         atomes, c'est-à-dire du savoir que le rappel ne servira jamais — n'était
         référencé nulle part dans ce fichier. Le moteur lui a pourtant donné sa
         propre requête, non bornée, précisément pour qu'aucune racine ne disparaisse
         du récit (today.py, _HL_ROOT_DEBT). Il porte une DETTE : il est donc placé
         avant les blocs neutres, et non en fin de page. */
      box.appendChild(highlightBlock('La dette posée sur une racine',
        'ces atomes existent en base et ne remonteront jamais dans un contexte servi — compte non borné, aucune racine n\'est tronquée',
        h.root_debt, [
          { label: 'territoire racine', cls: 't1', mono: true, nowrap: true, cell: function (s) {
              return el('span', {}, [
                el('span', { text: s.scope }),
                el('span', { class: 'chip', 'data-state': 'critical' },
                  [glyph('critical'), el('span', { text: 'invisible au rappel' })])
              ]);
            } },
          { label: 'atomes créés', field: 'atomes_crees', num: true }
        ], function (s) { return '#/scopes/' + s.scope; },
        'aucun atome n\'a été posé sur une racine sur cette fenêtre.'));

      box.appendChild(highlightBlock('Les conversations absorbées', 'ce qui est entré, et ce qui en a été tiré',
        h.absorbed_conversations, [
          { label: 'conversation', cls: 't1', cell: function (c) {
              return el('span', {}, [
                el('div', { text: c.title || '(sans titre)' }),
                el('div', { class: 'card-key', text: c.uid })
              ]);
            } },
          { label: 'source', field: 'source_type', mono: true, raw: true },
          { label: 'messages (fenêtre)', field: 'messages_fenetre', num: true },
          { label: 'messages (total)', field: 'messages_total', num: true },
          { label: 'atomes', field: 'atoms_generated', num: true },
          { label: 'entièrement curée', cell: function (c) {
              return c.entierement_curee ? stateChip('ok', 'oui') : stateChip('warn', 'non');
            } },
          { label: 'neuve', cell: function (c) { return c.conversation_neuve ? stateChip('ok', 'neuve') : el('span', { class: 'faint', text: '—' }); } },
          { label: 'reçue', nowrap: true, cell: function (c) { return fmtRel(c.created_at); } }
        ], function (c) { return '#/conversations/' + encodeURIComponent(c.uid); },
        'aucune conversation n\'a été absorbée sur cette fenêtre.'));

      box.appendChild(highlightBlock('Les passages du cerveau', 'le cerveau travaille quelques fois par jour — horaire OBSERVÉ dans les reçus',
        h.cycles, [
          { label: 'créneau', field: 'slot_key', mono: true, raw: true },
          { label: 'statut', cell: function (c) {
              return stateChip(c.status === 'done' ? 'ok' : (c.status === 'quarantined' || c.status === 'spawn_failed') ? 'critical' : 'warn', c.status);
            } },
          { label: 'modèle', field: 'model', mono: true, raw: true },
          { label: 'items', field: 'items', num: true },
          { label: 'atomes', field: 'atoms_created', num: true },
          { label: 'quarantaine', field: 'atoms_quarantined', num: true },
          { label: 'jetons', field: 'est_input_tokens', num: true },
          { label: 'arrêt', field: 'stop_reason', mono: true, raw: true },
          { label: 'début', nowrap: true, cell: function (c) { return fmtRel(c.started_at); } }
        ], null, 'aucun cycle n\'a tourné sur cette fenêtre.'));
    });
  }

  /* =======================================================================
     12quater · « SCOPES » — les territoires du savoir
     ======================================================================= */

  /* Les 6 états publiés par la LÉGENDE de /cc/v1/scopes/tree sont tous explicites.
     Le repli valait « ok » — vert : un état que l'interface ne comprend pas était
     donc affirmé sain. Même faute que le maillon « franchi » sur une perte non
     mesurée. Aucune teinte ne change sur les 38 territoires servis (actif et stable
     restent verts) ; seul un 7e état, s'il apparaissait, serait signalé au lieu
     d'être absous. Le mot affiché reste l'état brut servi. */
  function scopeStateTone(s) {
    if (s === 'dette') return 'critical';
    if (s === 'vide' || s === 'jamais_rappele') return 'unavailable';
    if (s === 'fragile') return 'warn';
    if (s === 'actif' || s === 'stable') return 'ok';
    return 'unavailable';
  }

  function viewScopesTree(host) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de l\'arbre des territoires…' }));
    host.appendChild(box);
    get(API + '/scopes/tree').then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'L\'arbre n\'a pas pu être lu', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') { box.appendChild(naBlock({ title: 'Arbre indisponible', reason: d.reason })); return; }
      var t = d.totals || {};

      box.appendChild(el('div', { class: 'toolbar' }, [
        el('span', { class: 'chip', text: fmtNum(t.scopes) + ' territoires' }),
        el('span', { class: 'chip', text: fmtNum(t.racines) + ' racines' }),
        el('span', { class: 'chip', 'data-state': 'warn' }, [glyph('warn'),
          el('span', { text: fmtNum(t.root_level_debt) + ' atomes en dette root-level' })]),
        el('span', { class: 'chip', text: fmtNum(t.dormant) + ' dormants · ' + fmtNum(t.dormant_pct) + ' %' }),
        el('span', { class: 'chip', text: 'confiance moyenne ' + fmtNum(t.confidence_avg) }),
        el('span', { class: 'chip', 'data-state': t.scopes_never_recalled ? 'warn' : 'ok' },
          [glyph(t.scopes_never_recalled ? 'warn' : 'ok'), el('span', { text: fmtNum(t.scopes_never_recalled) + ' jamais rappelés' })]),
        registerSqlEvidence('scopes-tree', d.evidence)
      ]));

      /* Regrouper par racine est de la PRÉSENTATION : la colonne `root` est
         servie, aucun nombre n'en sort. */
      var items = d.items || [];
      var roots = [], byRoot = {};
      items.forEach(function (s) {
        if (!hasOwn(byRoot, s.root)) { byRoot[s.root] = []; roots.push(s.root); }
        byRoot[s.root].push(s);
      });

      var tree = el('div', { class: 'stack' });
      roots.forEach(function (root) {
        var group = byRoot[root];
        var head = null, leaves = [];
        group.forEach(function (s) { if (s.is_root_scope) head = s; else leaves.push(s); });

        var rootLine = el('div', { class: 'scope-root' }, [
          el('span', { class: 'scope-branch', 'aria-hidden': 'true' }),
          head ? el('button', {
            class: 'scope-name q', type: 'button', 'data-go': '#/scopes/' + head.path,
            title: 'scope RACINE : ses atomes sont invisibles au rappel'
          }, [
            el('span', { class: 'mono', text: root }),
            el('span', { class: 'chip', 'data-state': 'critical' }, [glyph('critical'),
              el('span', { text: fmtNum(head.atoms_active) + ' atomes invisibles au rappel' })])
          ]) : el('span', { class: 'scope-name' }, el('span', { class: 'mono faint', text: root })),
          head ? null : el('span', { class: 'tiny faint', text: 'racine non peuplée — aucun atome n\'y est posé directement' })
        ]);
        tree.appendChild(rootLine);

        tree.appendChild(dataTable([
          { label: 'feuille', cls: 't1', mono: true, nowrap: true, cell: function (s) {
              return el('span', { class: 'scope-leaf' }, [
                el('span', { class: 'scope-branch', 'aria-hidden': 'true' }),
                el('span', { text: s.leaf })
              ]);
            } },
          { label: 'état', nowrap: true, cell: function (s) { return stateChip(scopeStateTone(s.state), s.state); } },
          { label: 'atomes', field: 'atoms_active', num: true },
          /* Les natures sont MONTRÉES, jamais comptées ici : le moteur sert le
             détail {nature: atomes} mais aucun total de natures pour cette
             ligne. Afficher `Object.keys(...).length` fabriquerait un chiffre
             du cerveau dans le navigateur — la faute exacte que ce cockpit
             refuse. Le compte de natures existe sur la fiche du territoire. */
          { label: 'natures', wrap: true, cell: function (s) {
              var kinds = s.kinds || {};
              var names = Object.keys(kinds);
              names.sort(function (a, b) { return kinds[b] - kinds[a]; });
              if (!names.length) return null;
              return el('span', {
                class: 'small mono',
                title: names.map(function (k) { return k + ' ' + fmtNum(kinds[k]); }).join(' · '),
                text: names.slice(0, 3).map(function (k) { return k + ' ' + fmtNum(kinds[k]); }).join(' · ') +
                      (names[3] ? ' …' : '')
              });
            } },
          { label: 'confiance', num: true, cell: function (s) {
              return el('span', { class: 'stack', style: 'gap:2px' }, [
                el('span', { class: 'mono', text: s.confidence_avg === null ? '—' : fmtNum(s.confidence_avg) }),
                bar(s.confidence_avg, s.confidence_avg !== null && s.confidence_avg < 80 ? 'warn' : 'ok')
              ]);
            } },
          { label: 'dormants', num: true, cell: function (s) {
              return el('span', { class: 'stack', style: 'gap:2px' }, [
                el('span', { class: 'mono', text: fmtNum(s.dormant) + ' · ' + fmtNum(s.dormant_pct) + ' %' }),
                bar(s.dormant_pct, 'na')
              ]);
            } },
          { label: 'rappels 30 j', field: 'recall_served_30d', num: true },
          { label: 'projets', wrap: true, cell: function (s) {
              return el('span', { class: 'small', text: (s.projects || []).join(' · ') || '—' });
            } },
          { label: 'dernier atome', nowrap: true, cell: function (s) { return fmtRel(s.last_atom_at); } }
        ], leaves, { href: function (s) { return '#/scopes/' + s.path; } }));
      });
      box.appendChild(tree);

      var legend = (d.legend || {}).state || {};
      var rows = [];
      for (var k in legend) { if (hasOwn(legend, k)) rows.push(el('dt', { text: k }), el('dd', { text: legend[k] })); }
      if (rows.length) box.appendChild(el('dl', { class: 'kv tiny', style: 'margin-top:16px' }, rows));
      if ((d.legend || {}).note) box.appendChild(el('p', { class: 'tiny faint', text: d.legend.note }));
    });
  }

  /* ---- sparkline : de la GÉOMÉTRIE, jamais un chiffre affiché ----------- */
  function sparkline(rows, xField, yField, label) {
    var W = 960, H = 120, PAD = 6;
    var root = svgBox('0 0 ' + W + ' ' + H, 'spark', label, true);
    var nb = rows.length;
    if (!nb) return root;
    /* La hauteur maximale sert d'échelle de tracé. C'est un choix de rendu :
       aucune valeur nouvelle n'apparaît à l'écran, et rien n'en est affiché. */
    var hi = 0;
    rows.forEach(function (r) { var v = r[yField]; if (typeof v === 'number' && v > hi) hi = v; });
    if (hi <= 0) hi = 1;
    var step = W / nb;
    root.appendChild(sv(root, 'line', { x1: 0, y1: H - PAD, x2: W, y2: H - PAD, class: 'spark-axis' }));
    rows.forEach(function (r, i) {
      var v = r[yField];
      if (typeof v !== 'number' || v <= 0) return;
      var h = (H - PAD - PAD) * v / hi;
      var b = sv(root, 'rect', {
        x: i * step, y: H - PAD - h, width: Math.max(step - 1, 0.6), height: h, class: 'spark-bar'
      });
      svTitle(root, b, String(r[xField]) + ' — ' + fmtNum(v));
      root.appendChild(b);
    });
    return root;
  }

  function viewScopeDetail(host, path) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture du territoire…' }));
    host.appendChild(box);
    get(API + '/scopes/' + path).then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Territoire illisible', reason: r.reason })); return; }
      var d = r.data || {};
      box.appendChild(el('div', { class: 'crumbs' }, [
        el('a', { href: '#/scopes', text: 'scopes' }), el('span', { class: 'sep', text: '/' }),
        el('span', { class: 'mono', text: path })
      ]));
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Territoire inconnu', reason: d.reason,
          gesture: 'vérifier le chemin — un scope s\'écrit « racine/feuille »' }));
        if (d.evidence) box.appendChild(sqlBlock('la requête qui n\'a rien trouvé', d.evidence.sql || '—'));
        return;
      }
      var h = d.header || {};

      box.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title mono', text: h.path }),
        el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
          stateChip(scopeStateTone(h.state), h.state),
          el('span', { class: 'chip', text: fmtNum(h.atoms_active) + ' atomes actifs' }),
          el('span', { class: 'chip', text: fmtNum(h.natures) + ' natures' }),
          el('span', { class: 'chip', text: 'confiance ' + fmtNum(h.confidence_avg) }),
          el('span', { class: 'chip', text: fmtNum(h.dormant_pct) + ' % dormants' }),
          el('button', { class: 'pill', type: 'button', 'data-go': '#/atomes' + qs({ scope: h.path }), text: '→ ses atomes' }),
          registerSqlEvidence('scope-' + path, d.evidence)
        ])
      ]));

      /* --- L'AVERTISSEMENT RACINE : la faute la plus coûteuse du système --- */
      var debt = d.debt || {};
      if (debt.is_root_scope) {
        box.appendChild(section('Ce territoire est une RACINE', null, naBlock({
          title: 'Atomes invisibles au rappel',
          reason: debt.raison,
          gesture: debt.gesture,
          substitute: 'ces atomes existent en base et restent lisibles ici — ils ne remontent jamais dans un contexte servi',
          impact: fmtNum(debt.atoms_invisible_au_rappel) + ' atomes actifs concernés'
        })));
      } else if (debt.raison) {
        box.appendChild(el('p', { class: 'tiny faint', text: debt.raison }));
      }

      /* --- ÉVOLUTION --- */
      var ev = d.evolution || [];
      box.appendChild(section('Son évolution',
        el('span', { class: 'tiny faint', text: 'atomes créés par jour · ' + fmtNum(d.evolution_window_days) + ' jours' }),
        ev.length ? el('div', { class: 'stack' }, [
          el('div', { class: 'spark-wrap' }, sparkline(ev, 'jour', 'atomes_crees', 'atomes créés par jour sur ce territoire')),
          el('div', { class: 'toolbar tiny faint' }, [
            el('span', { class: 'mono', text: (ev[0] || {}).jour }),
            el('span', { text: '→' }),
            el('span', { class: 'mono', text: (ev[ev.length - 1] || {}).jour }),
            el('span', { text: 'premier atome ' + fmtStamp(h.first_atom_at) + ' · dernier ' + fmtStamp(h.last_atom_at) })
          ])
        ]) : emptyBlock('Aucune évolution servie', 'le moteur n\'a pas produit de série pour ce territoire.')));

      /* --- COUVERTURE --- */
      var cov = d.coverage || {};
      box.appendChild(section('Ce qu\'il couvre',
        el('span', { class: 'tiny faint', text: 'natures structurantes : ' + (cov.structurantes || '—') }),
        el('div', { class: 'stack' }, [
          (cov.kinds || []).length ? dataTable([
            { label: 'nature', cls: 't1', mono: true, nowrap: true, cell: function (k) {
                return el('span', {}, [
                  el('span', { text: k.nature }),
                  k.structurante ? el('span', { class: 'chip', text: 'structurante' }) : null
                ]);
              } },
            { label: 'atomes', field: 'atomes', num: true },
            { label: 'part', num: true, cell: function (k) {
                return el('span', { class: 'stack', style: 'gap:2px' }, [
                  el('span', { class: 'mono', text: fmtNum(k.part_pct) + ' %' }),
                  bar(k.part_pct, '')
                ]);
              } },
            { label: 'confiance', field: 'confiance_moyenne', num: true },
            { label: 'avec rationnel', field: 'avec_rationnel', num: true },
            { label: 'dernier', nowrap: true, cell: function (k) { return fmtRel(k.dernier); } }
          ], cov.kinds, {}) : emptyBlock('Aucune nature', 'ce territoire ne porte aucun atome actif.'),
          cov.note ? el('p', { class: 'tiny faint', text: cov.note }) : null,
          (cov.tags || []).length ? el('div', { class: 'stack' }, [
            el('div', { class: 'eyebrow', text: 'ses étiquettes' }),
            el('div', { class: 'tags' }, cov.tags.map(function (t) {
              return el('span', { class: 'tag', title: fmtNum(t.atomes) + ' atomes · confiance ' + fmtNum(t.confiance_moyenne) + ' · dernier ' + fmtStamp(t.dernier),
                text: t.tag + ' ' + fmtNum(t.atomes) });
            }))
          ]) : null
        ])));

      /* --- CONFIANCE --- */
      var conf = d.confidence || {};
      box.appendChild(section('Où il doute',
        el('span', { class: 'tiny faint', text: conf.note || '' }),
        el('div', { class: 'stack' }, [
          (conf.distribution || []).length ? dataTable([
            { label: 'tranche', cls: 't1', mono: true, raw: true, field: 'tranche' },
            { label: 'atomes', field: 'atomes', num: true },
            { label: 'part', num: true, cell: function (x) {
                return el('span', { class: 'stack', style: 'gap:2px' }, [
                  el('span', { class: 'mono', text: fmtNum(x.part_pct) + ' %' }),
                  bar(x.part_pct, x.score_max !== null && x.score_max < 70 ? 'warn' : '')
                ]);
              } },
            { label: 'min', field: 'score_min', num: true },
            { label: 'max', field: 'score_max', num: true }
          ], conf.distribution, {}) : emptyBlock('Aucune distribution', 'aucun atome noté sur ce territoire.'),
          (conf.fragile || []).length ? el('div', { class: 'stack' }, [
            el('div', { class: 'eyebrow', text: 'ses souvenirs fragiles — score sous ' + fmtNum(conf.fragile_below) + ' ou sans score' }),
            dataTable([
              { label: 'nature', field: 'kind', mono: true, raw: true },
              { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
              { label: 'ce qu\'il dit', wrap: true, cell: function (a) { return el('span', { class: 'small', text: cut(a.extrait, 150) }); } },
              { label: 'score', field: 'confidence_score', num: true },
              { label: 'origine', field: 'confidence', mono: true, raw: true },
              { label: 'justifié', cell: function (a) { return a.justifie ? stateChip('ok', 'oui') : stateChip('warn', 'non'); } },
              { label: 'créé', nowrap: true, cell: function (a) { return fmtRel(a.created_at); } }
            ], conf.fragile, { href: function (a) { return '#/atomes/' + encodeURIComponent(a.id); } })
          ]) : null
        ])));

      /* --- RAPPEL --- */
      var rec = d.recall || {};
      box.appendChild(section('Ce que le rappel en fait', null, el('div', { class: 'stack' }, [
        el('dl', { class: 'kv' }, [
          el('dt', { text: 'rappels servis' }), el('dd', { class: 'mono', text: fmtNum(rec.served) }),
          el('dt', { text: 'atomes distincts servis' }), el('dd', { class: 'mono', text: fmtNum(rec.distinct_atoms) + ' / ' + fmtNum(rec.atoms_active) }),
          el('dt', { text: 'jamais servis' }), el('dd', { class: 'mono', text: fmtNum(rec.never_served) }),
          el('dt', { text: 'rappels 30 j' }), el('dd', { class: 'mono', text: fmtNum(rec.served_30d) }),
          el('dt', { text: 'dernier service' }), el('dd', { text: rec.last_served_at ? fmtStamp(rec.last_served_at) + ' · ' + fmtRel(rec.last_served_at) : 'jamais' })
        ]),
        kvFromObject('bandes de confiance du rappel', rec.bands),
        kvFromObject('qui le consomme', rec.consumers)
      ])));

      /* --- CONVERSATIONS · PROJETS · VOISINS · HISTOIRE --- */
      box.appendChild(section('D\'où il vient', null,
        (d.conversations || []).length ? dataTable([
          { label: 'conversation', cls: 't1', cell: function (c) {
              return el('span', {}, [el('div', { text: c.title || '(sans titre)' }), el('div', { class: 'card-key', text: c.uid })]);
            } },
          { label: 'source', field: 'source_type', mono: true, raw: true },
          { label: 'atomes ici', field: 'atomes', num: true },
          { label: 'confiance', field: 'confiance_moyenne', num: true },
          { label: 'curée', nowrap: true, cell: function (c) { return fmtRel(c.curated_at); } }
        ], d.conversations, { href: function (c) { return '#/conversations/' + encodeURIComponent(c.uid); } })
          : emptyBlock('Aucune conversation résolvable', 'aucun atome de ce territoire ne porte de conversation d\'origine retrouvable.')));

      if ((d.projects || []).length) {
        box.appendChild(section('Les projets qui s\'appuient dessus', null,
          el('div', { class: 'toolbar' }, d.projects.map(function (p) {
            return el('button', { class: 'pill', type: 'button', 'data-go': '#/projets/' + encodeURIComponent(p.id),
              text: '→ ' + p.label + ' · ' + fmtNum(p.atomes) + ' atomes' });
          }))));
      }

      var ns = d.neighbours_state || {};
      box.appendChild(section('Ses voisins', el('span', { class: 'tiny faint', text: ns.operator || '' }),
        (d.neighbours || []).length ? dataTable([
          { label: 'territoire', cls: 't1', mono: true, raw: true, field: 'path' },
          { label: 'distance', field: 'distance', num: true },
          { label: 'membres', field: 'member_count', num: true },
          { label: 'indexé', nowrap: true, cell: function (n) { return fmtRel(n.updated_at); } }
        ], d.neighbours, { href: function (n) { return '#/scopes/' + n.path; } })
          : naBlock({ title: 'Voisinage indisponible', reason: ns.reason || 'aucun voisin servi',
              substitute: 'un voisin n\'est pas un lien : c\'est une ressemblance calculée' })));

      box.appendChild(section('Son histoire', el('span', { class: 'tiny faint', text: d.history_note || '' }),
        (d.history || []).length ? dataTable([
          { label: 'quand', nowrap: true, cell: function (x) { return fmtRel(x.at); } },
          { label: 'horodatage', nowrap: true, cell: function (x) { return el('span', { class: 'ts', text: fmtStamp(x.at) }); } },
          { label: 'type', field: 'type', mono: true, raw: true },
          { label: 'quoi', wrap: true, field: 'label', raw: true, cls: 't1' }
        ], d.history, { href: function (x) { return hrefToHash(x.href); } })
          : emptyBlock('Aucun événement', 'le moteur n\'a retrouvé aucun fait daté sur ce territoire.')));
    });
  }

  function kvFromObject(title, obj) {
    if (!obj) return null;
    var rows = [];
    for (var k in obj) { if (hasOwn(obj, k)) rows.push(el('dt', { class: 'mono', text: k }), el('dd', { class: 'mono', text: fmtNum(obj[k]) })); }
    if (!rows.length) return null;
    return el('div', { class: 'stack' }, [el('div', { class: 'eyebrow', text: title }), el('dl', { class: 'kv' }, rows)]);
  }

  /* Traduit un chemin d'API servi en route d'écran. Un chemin inconnu ne
     produit AUCUN lien : on ne devine pas un écran qui n'existe pas. */
  function hrefToHash(href) {
    if (!href) return null;
    /* Les destinations SERVIES avec un filtre — `/cc/v1/atoms?scope=…`, `?q=…` —
       étaient rendues intraduisibles, donc inertes : 15 nœuds sur 55 du graphe de
       projet (le scope et les 14 thèmes) n'avaient ni bouton « → ouvrir », ni ligne
       cliquable dans le tableau de repli. L'écran d'arrivée existe pourtant :
       `viewAtomes` lit `scope` et `q` dans la query de la route. Ne jamais laisser
       une destination servie sans issue. */
    var f = /^\/cc\/v1\/atoms\?(.+)$/.exec(href);
    if (f) return '#/atomes?' + f[1];
    var m = /^\/cc\/v1\/(atoms|conversations|projects|scopes)\/(.+)$/.exec(href);
    if (!m) return null;
    var rest = m[2].replace(/\/story$/, '').replace(/\/graph$/, '');
    if (m[1] === 'atoms') return '#/atomes/' + rest;
    /* NOTE : `/cc/v1/metrics/<clé>` n'a pas d'écran propre — son écran d'arrivée est
       le TIROIR de preuve, qui n'est pas une route de hash. Il se traite donc par
       `metricKeyFromHref()` là où il est servi, pas ici. */
    if (m[1] === 'conversations') return '#/conversations/' + rest;
    if (m[1] === 'projects') return '#/projets/' + rest;
    return '#/scopes/' + rest;
  }

  /* Le moteur sert `/cc/v1/metrics/<clé>` comme destination d'un événement de
     chronologie (208 rappels et 11 cycles sur 263 lignes, soit 83 % du tableau).
     `hrefToHash` ne sait pas la traduire — et pour cause : la destination n'est pas
     un écran, c'est le tiroir de preuve, ouvert par `data-metric`. Faute de ce
     pont, 83 % des lignes restaient inertes alors que l'arrivée existait déjà. */
  function metricKeyFromHref(href) {
    if (!href) return null;
    var m = /^\/cc\/v1\/metrics\/([^?#]+)/.exec(href);
    if (!m) return null;
    try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
  }

  /* =======================================================================
     12quinquies · « ATOMES » — les vues comptées par le moteur
     -----------------------------------------------------------------------
     Chaque onglet EST une métrique du domaine « atomes » : son compte vient du
     registre, ses lignes viennent de sa requête de preuve. Le cockpit ne compte
     rien et ne filtre rien lui-même.

     Les vues indisponibles (orphelins de graphe, contradictoires) restent
     VISIBLES et marquées. Les masquer laisserait croire que le cerveau les
     mesure et n'en trouve aucune — c'est exactement l'inverse.
     ======================================================================= */

  /* Ordre d'apparition des onglets. Ce sont des CLÉS de métriques, pas des
     valeurs : le libellé et le compte de chacun viennent du moteur. Toute clé
     du domaine absente de cette liste est ajoutée à la fin — aucune vue ne peut
     disparaître de l'écran parce qu'on aurait oublié de la nommer ici. */
  var ATOM_VIEW_ORDER = [
    'view_new_24h', 'view_enriched', 'view_merged', 'view_never_recalled',
    'view_recalled_7d', 'view_load_bearing', 'view_root_debt', 'view_missing_rationale',
    'view_cornerstone', 'view_project_orphans', 'view_graph_orphans', 'view_contradictory'
  ];

  function orderedAtomViews() {
    var list = metricsOf('atomes');
    var seen = {}, out = [];
    ATOM_VIEW_ORDER.forEach(function (k) {
      list.forEach(function (m) { if (m.key === k && !seen[k]) { seen[k] = 1; out.push(m); } });
    });
    list.forEach(function (m) { if (!seen[m.key]) { seen[m.key] = 1; out.push(m); } });
    return out;
  }

  function atomViewsSection(host, q) {
    var views = orderedAtomViews();
    if (!views.length) {
      host.appendChild(section('Les vues du savoir', null, emptyBlock(
        'Aucune vue publiée', 'le registre ne publie aucune métrique du domaine « atomes ».')));
      return;
    }
    var current = q.vue || views[0].key;
    var found = false;
    views.forEach(function (m) { if (m.key === current) found = true; });
    if (!found) current = views[0].key;

    var tabs = el('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Vues du savoir' });
    views.forEach(function (m) {
      var st = m.state || 'unavailable';
      var na = st === 'unavailable';
      var b = el('button', {
        class: 'tab q', type: 'button', role: 'tab', 'data-state': st,
        'aria-selected': m.key === current ? 'true' : 'false',
        title: m.definition + (na && m.reason ? '\n\n' + m.reason : '') + '\n\nun clic ouvre cette vue'
      }, [
        glyph(st),
        el('span', { class: 'tab-name', text: m.label }),
        el('span', { class: 'tab-count', text: na ? '—' : fmtNum(m.value) })
      ]);
      b.addEventListener('click', function () { navPatch({ vue: m.key }); });
      tabs.appendChild(b);
    });

    var body = el('div', { class: 'stack' });
    host.appendChild(section('Les vues du savoir',
      el('span', { class: 'tiny faint', text: 'chaque onglet porte le compte servi par le moteur ; « — » signale une vue non mesurable, jamais un zéro' }),
      el('div', { class: 'stack' }, [tabs, body])));
    evidenceSection(body, current, { title: 'Ce que cette vue contient', limit: 80,
      naTitle: 'Cette vue n\'est pas mesurable' });
  }

  /* =======================================================================
     12sexies · L'HISTOIRE D'UN ATOME — /cc/v1/atoms/{id}/story
     ======================================================================= */

  function viewAtomeStory(host, id) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de l\'histoire de l\'atome…' }));
    host.appendChild(box);
    get(API + '/atoms/' + encodeURIComponent(id) + '/story').then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'Histoire illisible', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Atome inconnu', reason: d.reason, gesture: 'vérifier l\'identifiant (uuid attendu)' }));
        if (d.evidence) box.appendChild(sqlBlock('la requête qui n\'a rien trouvé', d.evidence.sql || '—'));
        return;
      }
      var i = d.identity || {}, c = d.content || {}, b = d.birth || {};

      box.appendChild(el('div', { class: 'crumbs' }, [
        el('a', { href: '#/atomes', text: 'atomes' }), el('span', { class: 'sep', text: '/' }),
        el('a', { href: '#/scopes/' + (i.scope || ''), text: i.scope || '—' }),
        el('span', { class: 'sep', text: '/' }), el('span', { class: 'mono', text: cut(i.key, 60) })
      ]));
      box.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title mono', text: i.key || id }),
        el('div', { class: 'toolbar', style: 'margin-top:8px' }, [
          stateChip(i.status === 'active' ? 'ok' : i.status === 'superseded' ? 'warn' : 'unavailable', i.status),
          el('span', { class: 'chip', text: i.kind || '—' }),
          el('span', { class: 'chip', text: 'v' + fmtNum(i.version) }),
          el('span', { class: 'chip', text: 'confiance ' + fmtNum(i.confidence_score) + ' · ' + (i.confidence || '—') }),
          i.is_root_scoped ? el('span', { class: 'chip', 'data-state': 'critical' },
            [glyph('critical'), el('span', { text: 'scope racine — invisible au rappel' })]) : null,
          i.retouche_sur_place ? el('span', { class: 'chip', 'data-state': 'warn' },
            [glyph('warn'), el('span', { text: 'retouché sur place' })]) : null,
          atomeVueToggle('histoire'),
          registerSqlEvidence('story-' + id, d.evidence)
        ])
      ]));

      box.appendChild(section('Ce qu\'il dit', null, el('div', { class: 'stack' }, [
        el('p', { class: 'excerpt', text: c.value || '—' }),
        c.rationale ? el('div', { class: 'stack' }, [
          el('div', { class: 'eyebrow', text: 'pourquoi' }),
          el('p', { class: 'excerpt tiny faint', text: c.rationale })
        ]) : el('p', { class: 'small muted', text: 'Aucun rationnel : ce souvenir affirme sans dire pourquoi — il ne peut être ni rejoué, ni contesté.' }),
        (i.tags && i.tags.length) ? el('div', { class: 'tags' }, i.tags.map(function (t) { return el('span', { class: 'tag', text: t }); })) : null
      ])));

      /* --- NAISSANCE --- */
      var cyc = b.cycle || {};
      box.appendChild(section('Sa naissance', el('span', { class: 'tiny faint', text: fmtStamp(b.at) + ' · ' + fmtRel(b.at) }),
        el('div', { class: 'stack' }, [
          el('div', { class: 'toolbar' }, [
            b.conversation_uid ? el('button', { class: 'pill', type: 'button',
              'data-go': '#/conversations/' + encodeURIComponent(b.conversation_uid),
              text: '→ ' + cut(b.conversation_title || b.conversation_uid, 56) }) : null,
            b.conversation_source_type ? el('span', { class: 'chip', text: b.conversation_source_type }) : null,
            b.run_id ? el('span', { class: 'chip', text: 'cycle ' + b.run_id }) : null
          ]),
          !b.conversation_uid ? el('p', { class: 'small muted', text: 'Aucune conversation d\'origine résolvable pour ce souvenir.' }) : null,
          cyc.id ? el('dl', { class: 'kv' }, [
            el('dt', { text: 'statut du cycle' }), el('dd', {}, stateChip(cyc.status === 'done' ? 'ok' : 'warn', cyc.status)),
            el('dt', { text: 'modèle' }), el('dd', { class: 'mono', text: cyc.model || '—' }),
            el('dt', { text: 'items du passage' }), el('dd', { class: 'mono', text: fmtNum(cyc.items) }),
            el('dt', { text: 'atomes du passage' }), el('dd', { class: 'mono', text: fmtNum(cyc.atoms_created) + ' créés · ' + fmtNum(cyc.atoms_superseded) + ' remplacés · ' + fmtNum(cyc.atoms_quarantined) + ' en quarantaine' }),
            el('dt', { text: 'jetons du passage' }), el('dd', { class: 'mono', text: fmtNum(cyc.est_input_tokens) }),
            el('dt', { text: 'durée' }), el('dd', { text: fmtStamp(cyc.started_at) + ' → ' + fmtStamp(cyc.ended_at) })
          ]) : null,
          el('dl', { class: 'kv' }, [
            el('dt', { text: 'nœud' }), el('dd', { class: 'mono', text: b.node_id || '—' }),
            el('dt', { text: 'audit' }), el('dd', { class: 'mono', text: b.audit_source || 'aucun' }),
            el('dt', { text: 'source_ref' }), el('dd', { class: 'mono tiny', text: b.source_ref ? JSON.stringify(b.source_ref) : '—' })
          ])
        ])));

      /* --- ENRICHISSEMENTS --- */
      box.appendChild(section('Ses enrichissements', el('span', { class: 'tiny faint', text: d.enrichments_note || '' }),
        (d.enrichments || []).length ? dataTable([
          { label: 'version', field: 'version', num: true },
          { label: 'quand', nowrap: true, cell: function (e) { return fmtRel(e.at); } },
          { label: 'ce qui a changé', wrap: true, cls: 't1', field: 'diff_summary', raw: true },
          { label: 'statut', field: 'status', mono: true, raw: true },
          { label: 'cycle', field: 'run_id', mono: true, raw: true },
          { label: 'celui-ci', cell: function (e) { return e.est_cet_atome ? stateChip('ok', 'cette version') : el('span', { class: 'faint', text: '—' }); } }
        ], d.enrichments, { href: function (e) { return e.est_cet_atome ? null : '#/atomes/' + encodeURIComponent(e.id); } })
          : emptyBlock('Aucun enrichissement', 'ce souvenir n\'a jamais été réécrit.')));

      /* --- LIGNÉE --- */
      var lin = d.lineage || {};
      var linRows = (lin.ancestors || []).concat(lin.descendants || []);
      box.appendChild(section('Sa lignée', el('span', { class: 'tiny faint', text: lin.note || '' }),
        linRows.length ? dataTable([
          { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
          { label: 'statut', field: 'status', mono: true, raw: true },
          { label: 'version', field: 'version', num: true },
          { label: 'saut', field: 'hop', num: true },
          { label: 'créée', nowrap: true, cell: function (v) { return fmtRel(v.created_at); } }
        ], linRows, { href: function (v) { return '#/atomes/' + encodeURIComponent(v.id); } })
          : emptyBlock('Aucune lignée', 'ce souvenir ne remplace rien et n\'est remplacé par rien.')));

      /* --- USAGE RÉEL --- */
      var u = d.usage || {};
      box.appendChild(section('Son usage réel',
        el('span', { class: 'tiny faint', text: u.never_served ? 'ce savoir dort : personne ne l\'a jamais reçu' : '' }),
        el('div', { class: 'stack' }, [
          el('dl', { class: 'kv' }, [
            el('dt', { text: 'servi' }), el('dd', { class: 'mono', text: u.never_served ? 'jamais' : fmtNum(u.served_count) + ' fois' }),
            el('dt', { text: 'premier service' }), el('dd', { text: u.first_served_at ? fmtStamp(u.first_served_at) : '—' }),
            el('dt', { text: 'dernier service' }), el('dd', { text: u.last_served_at ? fmtStamp(u.last_served_at) + ' · ' + fmtRel(u.last_served_at) : '—' })
          ]),
          (u.queries || []).length ? dataTable([
            { label: 'consommateur', field: 'consumer', mono: true, raw: true },
            { label: 'bande', field: 'final_band', mono: true, raw: true },
            { label: 'arrêt', field: 'stop_reason', mono: true, raw: true },
            { label: 'quand', nowrap: true, cell: function (x) { return fmtRel(x.created_at); } }
          ], u.queries, {}) : null,
          u.queries_truncated ? el('p', { class: 'tiny faint', text: 'liste des requêtes tronquée par le moteur.' }) : null
        ])));

      /* --- SCOPES · PROJETS --- */
      if ((d.scopes_using || []).length) {
        box.appendChild(section('Les territoires qui s\'en servent', null, dataTable([
          { label: 'territoire', cls: 't1', mono: true, raw: true, field: 'scope' },
          { label: 'atomes', field: 'atomes', num: true }
        ], d.scopes_using, { href: function (s) { return '#/scopes/' + s.scope; } })));
      }
      if ((d.projects_depending || []).length) {
        box.appendChild(section('Les projets qui en dépendent', null, el('div', { class: 'stack' },
          d.projects_depending.map(function (p) {
            var rule = p.rule || {};
            return el('div', { class: 'stack', style: 'gap:4px' }, [
              el('div', { class: 'toolbar' }, [
                el('button', { class: 'pill', type: 'button', 'data-go': '#/projets/' + encodeURIComponent(p.id), text: '→ ' + p.label }),
                el('span', { class: 'tiny faint mono', text: 'règle : scopes ' + JSON.stringify(rule.scopes || []) +
                  ((rule.keywords || []).length ? ' · mots-clés ' + JSON.stringify(rule.keywords) : '') + ' · ' + (rule.combination || '') })
              ])
            ]);
          }))));
      }

      /* --- VOISINS --- */
      var ns = d.neighbours_state || {};
      box.appendChild(section('Ses voisins sémantiques',
        el('span', { class: 'tiny faint', text: (ns.operator || '') + ' · ' + (ns.note || '') }),
        (d.neighbours || []).length ? dataTable([
          { label: 'distance', field: 'distance', num: true },
          { label: 'nature', field: 'kind', mono: true, raw: true },
          { label: 'territoire', field: 'scope', mono: true, raw: true },
          { label: 'clé', cls: 't1', mono: true, raw: true, field: 'key' },
          { label: 'statut', field: 'status', mono: true, raw: true }
        ], d.neighbours, { href: function (n) { return '#/atomes/' + encodeURIComponent(n.id); } })
          : naBlock({ title: 'Voisinage indisponible', reason: ns.reason || 'aucun voisin servi' })));

      /* --- CE QUI N'EST PAS MESURABLE — affiché, jamais tu --- */
      if (d.links && d.links.state === 'unavailable') {
        box.appendChild(section('Ses liens', null, naBlock({
          title: 'Maillon « Reliée » — organe non branché', reason: d.links.reason,
          gesture: d.links.gesture, substitute: d.links.substitute, impact: d.links.impact,
          source: 'arac.atom_links'
        })));
      }
      if (d.verification && d.verification.state === 'unavailable') {
        box.appendChild(section('Sa vérification', null, naBlock({
          title: 'Mécanisme non alimenté', reason: d.verification.reason,
          gesture: d.verification.gesture, substitute: d.verification.substitute,
          source: 'memory_atoms.last_verified_at / confirmed_until'
        })));
      }

      /* --- CHRONOLOGIE --- */
      box.appendChild(section('Sa chronologie',
        d.timeline_truncated ? el('span', { class: 'tiny faint', text: 'chronologie tronquée par le moteur' }) : null,
        (d.timeline || []).length ? dataTable([
          { label: 'quand', nowrap: true, cell: function (t) { return fmtRel(t.at); } },
          { label: 'horodatage', nowrap: true, cell: function (t) { return el('span', { class: 'ts', text: fmtStamp(t.at) }); } },
          { label: 'type', field: 'type', mono: true, raw: true },
          { label: 'quoi', wrap: true, cls: 't1', field: 'label', raw: true }
        ], d.timeline, { href: function (t) { return hrefToHash(t.href); } })
          : emptyBlock('Aucun fait daté', 'le moteur n\'a retrouvé aucun événement pour ce souvenir.')));
    });
  }

  /* =======================================================================
     12septies · « PROJETS » — le graphe vivant, en SVG, sans bibliothèque
     -----------------------------------------------------------------------
     Le moteur sert des NŒUDS (avec leur poids), des ARÊTES (avec leur nature et
     leur distance) et la PROVENANCE de chaque nature d'arête. Le cockpit ne fait
     que placer ces nœuds : angles, rayons, épaisseurs. Aucune de ces quantités
     n'est une mesure du cerveau, aucune n'est affichée comme un chiffre.

     AUCUNE ARÊTE N'EST UN LIEN DÉCLARÉ — rien ici ne lit `arac.atom_links`. Le
     graphe le dit à l'écran, en toutes lettres, sous la figure. Laisser croire
     à un graphe de sens serait le mensonge le plus rentable de cet écran.
     ======================================================================= */

  var GRAPH = { id: null, data: null, expand: 1, focus: null, host: null };

  var GRAPH_PER_SECTOR = 12;   // atomes dépliés par territoire et par palier
  var GRAPH_RINGS = 4;         // couronnes d'atomes par secteur

  function graphLayout(data, expand) {
    var W = 1000, H = 700, CX = 500, CY = 350;
    var TWO_PI = Math.PI * 2;
    var nodes = (data && data.nodes) || [];
    var pos = {}, placed = [];

    var project = null, scopes = [], themes = [], atoms = [];
    nodes.forEach(function (n) {
      if (n.kind === 'project') { if (!project) project = n; }
      else if (n.kind === 'scope') scopes.push(n);
      else if (n.kind === 'theme') themes.push(n);
      else atoms.push(n);
    });

    /* Trier sur une colonne SERVIE (le poids) reste de la présentation : les
       plus portants d'abord, pour qu'un dépliage partiel montre l'essentiel. */
    function byWeight(a, b) { return (b.weight || 0) - (a.weight || 0); }
    scopes.sort(byWeight); themes.sort(byWeight); atoms.sort(byWeight);

    function put(n, x, y, ring) { pos[n.id] = { x: x, y: y, node: n, ring: ring }; placed.push(pos[n.id]); }

    if (project) put(project, CX, CY, 'project');

    var sectors = {}, nbSectors = Math.max(scopes.length, 1);
    var sectorSpan = TWO_PI / nbSectors;
    scopes.forEach(function (s, i) {
      var ang = i * sectorSpan - Math.PI / 2;
      sectors[s.scope || s.label] = ang;
      put(s, CX + Math.cos(ang) * 140, CY + Math.sin(ang) * 140, 'scope');
    });

    var nbThemes = Math.max(themes.length, 1);
    themes.forEach(function (t, i) {
      var ang = i * (TWO_PI / nbThemes) - Math.PI / 2 + sectorSpan / 2;
      put(t, CX + Math.cos(ang) * 235, CY + Math.sin(ang) * 235, 'theme');
    });

    /* Les atomes se rangent dans le secteur de LEUR territoire (colonne servie).
       Un dépliage progressif borne le nombre placé par secteur. */
    var perSector = {}, budget = GRAPH_PER_SECTOR * expand;
    var hidden = 0;
    atoms.forEach(function (a) {
      var key = hasOwn(sectors, a.scope) ? a.scope : '#autres';
      if (!hasOwn(perSector, key)) perSector[key] = [];
      perSector[key].push(a);
    });
    var otherAng = -Math.PI / 2 + sectorSpan / 2;
    for (var key in perSector) {
      if (!hasOwn(perSector, key)) continue;
      var list = perSector[key];
      var base = hasOwn(sectors, key) ? sectors[key] : otherAng;
      var take = Math.min(list.length, budget);
      hidden = hidden + (list.length - take);
      for (var j = 0; j < take; j++) {
        var ring = j % GRAPH_RINGS;
        var slot = Math.floor(j / GRAPH_RINGS);
        var perRing = Math.ceil(take / GRAPH_RINGS);
        var spread = sectorSpan * 0.82;
        var a2 = base - spread / 2 + (perRing <= 1 ? spread / 2 : spread * slot / (perRing - 1));
        var rad = 300 + ring * 48;
        put(list[j], CX + Math.cos(a2) * rad, CY + Math.sin(a2) * rad, 'atom');
      }
    }
    return { W: W, H: H, pos: pos, placed: placed, hidden: hidden,
             counts: { scopes: scopes.length, themes: themes.length, atoms: atoms.length } };
  }

  function nodeRadius(n) {
    if (n.kind === 'project') return 20;
    if (n.kind === 'scope') return 13;
    if (n.kind === 'theme') return 8;
    var w = typeof n.weight === 'number' ? n.weight : 0;
    return Math.min(4 + Math.sqrt(w) * 0.55, 15);
  }

  function renderGraph(host, data, expand, focus) {
    clear(host);
    var lay = graphLayout(data, expand);
    var root = svgBox('0 0 ' + lay.W + ' ' + lay.H, 'graph',
      'Graphe du projet ' + ((data.project || {}).label || '') + ' — nœuds et rapprochements');

    /* --- les arêtes d'abord : elles passent SOUS les nœuds --- */
    var edges = data.edges || [];
    var gEdges = sv(root, 'g', { class: 'g-edges' });
    edges.forEach(function (e) {
      var a = lay.pos[e.source], b = lay.pos[e.target];
      if (!a || !b) return;
      var touched = focus && (e.source === focus || e.target === focus);
      gEdges.appendChild(sv(root, 'line', {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        class: 'g-edge', 'data-kind': e.kind,
        'data-focus': focus ? (touched ? 'on' : 'off') : ''
      }));
    });
    root.appendChild(gEdges);

    /* --- puis les nœuds --- */
    var gNodes = sv(root, 'g', { class: 'g-nodes' });
    lay.placed.forEach(function (p) {
      var n = p.node;
      var isFocus = focus === n.id;
      var dim = focus && !isFocus && !graphTouches(edges, focus, n.id);
      var g = sv(root, 'g', {
        class: 'g-node', 'data-kind': n.kind, 'data-focus': isFocus ? 'on' : (dim ? 'off' : ''),
        tabindex: '0', role: 'button',
        'aria-label': n.kind + ' ' + n.label + ' — poids ' + fmtNum(n.weight)
      });
      var circle = sv(root, 'circle', { cx: p.x, cy: p.y, r: nodeRadius(n), class: 'g-dot' });
      svTitle(root, circle, n.kind + ' · ' + n.label + '\npoids servi : ' + fmtNum(n.weight) +
        (n.scope ? '\nterritoire : ' + n.scope : '') + (n.atom_kind ? '\nnature : ' + n.atom_kind : ''));
      g.appendChild(circle);
      if (n.kind !== 'atom' || isFocus) {
        g.appendChild(sv(root, 'text', {
          x: p.x, y: p.y - nodeRadius(n) - 6, class: 'g-label', 'text-anchor': 'middle'
        }, cut(n.label, n.kind === 'project' ? 40 : 26)));
      }
      var act = function () {
        GRAPH.focus = (GRAPH.focus === n.id) ? null : n.id;
        renderGraph(host, data, GRAPH.expand, GRAPH.focus);
      };
      g.addEventListener('click', act);
      g.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); }
      });
      gNodes.appendChild(g);
    });
    root.appendChild(gNodes);
    host.appendChild(el('div', { class: 'graph-wrap' }, root));

    /* --- ce que le focus a ouvert : la fiche du nœud choisi --- */
    if (focus && lay.pos[focus]) {
      var fn = lay.pos[focus].node;
      var hash = hrefToHash(fn.href);
      host.appendChild(el('div', { class: 'graph-focus' }, [
        el('span', { class: 'eyebrow', text: 'nœud choisi' }),
        el('span', { class: 'mono', text: fn.label }),
        el('span', { class: 'chip', text: fn.kind }),
        fn.scope ? el('span', { class: 'chip', text: fn.scope }) : null,
        fn.atom_kind ? el('span', { class: 'chip', text: fn.atom_kind }) : null,
        el('span', { class: 'tiny faint', text: 'poids ' + fmtNum(fn.weight) + ' · du ' + fmtStamp(fn.first_at) + ' au ' + fmtStamp(fn.last_at) }),
        hash ? el('button', { class: 'pill', type: 'button', 'data-go': hash, text: '→ ouvrir' }) : null
      ]));
    }

    /* --- les commandes de dépliage --- */
    var tools = el('div', { class: 'toolbar' });
    if (lay.hidden > 0) {
      var more = el('button', { class: 'pill', type: 'button', text: '+ déplier davantage d\'atomes' });
      more.addEventListener('click', function () { GRAPH.expand = GRAPH.expand + 1; renderGraph(host, data, GRAPH.expand, GRAPH.focus); });
      tools.appendChild(more);
      var all = el('button', { class: 'pill', type: 'button', text: 'tout déplier' });
      all.addEventListener('click', function () { GRAPH.expand = 9999; renderGraph(host, data, GRAPH.expand, GRAPH.focus); });
      tools.appendChild(all);
      /* Un dépliage partiel CACHE aussi des arêtes : celles qui rejoignent un
         atome non déplié ne peuvent pas être tracées. Le taire laisserait lire
         la figure comme un graphe complet — on le dit donc à côté du geste. */
      tools.appendChild(el('span', { class: 'chip', 'data-state': 'unavailable' }, [
        glyph('unavailable'),
        el('span', { text: String(lay.hidden) + ' atomes servis mais non dépliés — les arêtes tracées sont seulement celles qui relient deux nœuds dépliés' })
      ]));
    }
    if (expand > 1) {
      var less = el('button', { class: 'pill', type: 'button', text: '− replier' });
      less.addEventListener('click', function () { GRAPH.expand = 1; renderGraph(host, data, 1, GRAPH.focus); });
      tools.appendChild(less);
    }
    if (focus) {
      var clr = el('button', { class: 'pill', type: 'button', text: 'quitter le focus' });
      clr.addEventListener('click', function () { GRAPH.focus = null; renderGraph(host, data, GRAPH.expand, null); });
      tools.appendChild(clr);
    }
    host.appendChild(tools);
  }

  function graphTouches(edges, focus, id) {
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (e.source === focus && e.target === id) return true;
      if (e.target === focus && e.source === id) return true;
    }
    return false;
  }

  function graphLegend(prov) {
    prov = prov || {};
    var rows = [];
    ['contains', 'lineage', 'semantic'].forEach(function (k) {
      if (!prov[k]) return;
      var root = svgBox('0 0 60 12', 'g-key', null, false);
      root.appendChild(sv(root, 'line', { x1: 2, y1: 6, x2: 58, y2: 6, class: 'g-edge', 'data-kind': k }));
      rows.push(el('div', { class: 'g-legend-row' }, [
        root, el('span', { class: 'mono tiny', text: k }), el('span', { class: 'tiny faint', text: prov[k] })
      ]));
    });
    return el('div', { class: 'stack' }, [
      el('div', { class: 'stack', style: 'gap:4px' }, rows),
      prov.operator ? el('p', { class: 'tiny faint', text: 'opérateur : ' + prov.operator }) : null,
      prov.avertissement ? naBlock({
        title: 'Ces arêtes ne sont PAS des liens déclarés',
        reason: prov.avertissement,
        substitute: 'appartenance de territoire, supersession et proximité vectorielle — rien d\'autre'
      }) : null
    ]);
  }

  function projectGraphSection(host, id) {
    var body = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture du graphe…' }));
    host.appendChild(section('Son graphe vivant',
      el('span', { class: 'tiny faint', text: 'un clic sur un nœud le met au foyer ; les nœuds sont au clavier' }), body));
    get(API + '/projects/' + encodeURIComponent(id) + '/graph').then(function (r) {
      clear(body);
      if (!r.ok) { body.appendChild(naBlock({ title: 'Graphe illisible', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') { body.appendChild(naBlock({ title: 'Graphe indisponible', reason: d.reason })); return; }
      if (GRAPH.id !== id) { GRAPH.id = id; GRAPH.expand = 1; GRAPH.focus = null; }
      GRAPH.data = d;

      var t = d.totals || {}, tr = d.truncated || {};
      body.appendChild(el('div', { class: 'toolbar' }, [
        el('span', { class: 'chip', text: fmtNum(t.membres) + ' membres' }),
        el('span', { class: 'chip', text: fmtNum(t.scopes) + ' territoires' }),
        el('span', { class: 'chip', text: fmtNum(t.themes) + ' thèmes' }),
        el('span', { class: 'chip', text: fmtNum(tr.shown) + ' nœuds servis sur ' + fmtNum(tr.total) }),
        el('span', { class: 'chip', text: fmtNum(tr.edges_shown) + ' arêtes servies' }),
        t.sans_plongement ? el('span', { class: 'chip', 'data-state': 'warn' }, [glyph('warn'),
          el('span', { text: fmtNum(t.sans_plongement) + ' atomes sans plongement — invisibles au voisinage' })]) : null,
        registerSqlEvidence('graph-' + id, d.evidence)
      ]));

      if (tr.applied || tr.edges_applied) {
        body.appendChild(naBlock({
          title: 'Le moteur a tronqué ce graphe',
          reason: 'nœuds servis ' + fmtNum(tr.shown) + ' sur ' + fmtNum(tr.total) + ' (borne ' + fmtNum(tr.limit) + ')' +
                  ' · arêtes ' + fmtNum(tr.edges_shown) + ' (borne ' + fmtNum(tr.edges_limit) + ')',
          substitute: (tr.kept || '') + (tr.edges_kept ? ' · ' + tr.edges_kept : '')
        }));
      }

      var canvas = el('div', { class: 'stack' });
      body.appendChild(canvas);
      renderGraph(canvas, d, GRAPH.expand, GRAPH.focus);

      body.appendChild(el('div', { class: 'hr' }));
      body.appendChild(graphLegend(d.edges_provenance));

      if (d.links && d.links.state === 'unavailable') {
        body.appendChild(naBlock({
          title: 'Le graphe DÉCLARÉ n\'existe pas', reason: d.links.reason,
          gesture: d.links.gesture, substitute: d.links.substitute, impact: d.links.impact,
          source: 'arac.atom_links'
        }));
      }

      /* La croissance du projet : géométrie seule, les valeurs viennent du SQL. */
      if ((d.growth || []).length) {
        body.appendChild(el('div', { class: 'hr' }));
        body.appendChild(el('div', { class: 'stack' }, [
          el('div', { class: 'eyebrow', text: 'sa croissance · ' + fmtNum(d.growth_window_days) + ' jours' }),
          el('div', { class: 'spark-wrap' }, sparkline(d.growth, 'jour', 'atomes', 'atomes gagnés par jour')),
          el('p', { class: 'tiny faint', text: d.growth_note || '' })
        ]));
      }

      /* Repli non graphique : les mêmes nœuds, en tableau, atteignables au
         clavier et lisibles par un lecteur d'écran. Aucun état ne repose sur
         la seule couleur de la figure. */
      body.appendChild(el('div', { class: 'hr' }));
      body.appendChild(el('div', { class: 'stack' }, [
        el('div', { class: 'eyebrow', text: 'les mêmes nœuds, en toutes lettres' }),
        dataTable([
          { label: 'genre', field: 'kind', mono: true, raw: true, nowrap: true },
          { label: 'nœud', cls: 't1', mono: true, raw: true, field: 'label' },
          { label: 'poids servi', field: 'weight', num: true },
          { label: 'territoire', field: 'scope', mono: true, raw: true },
          { label: 'nature', field: 'atom_kind', mono: true, raw: true },
          { label: 'du', nowrap: true, cell: function (n) { return fmtRel(n.first_at); } },
          { label: 'au', nowrap: true, cell: function (n) { return fmtRel(n.last_at); } }
        ], d.nodes || [], { href: function (n) { return hrefToHash(n.href); } })
      ]));
    });
  }

  /* =======================================================================
     12octies · « CONFIANCE » — où le cerveau doute
     ======================================================================= */

  function viewConfiance(host) {
    var list = metricsOf('confiance');
    host.appendChild(section('Ce que le cerveau sait de son propre doute',
      el('span', { class: 'tiny faint', text: list.length ? plural(list.length, 'mesure') + ' · un clic ouvre la preuve' : '' }),
      list.length ? metricGrid(list)
        : emptyBlock('Aucune mesure de confiance', 'le registre n\'en publie aucune.')));

    evidenceSection(host, 'confidence_median', { title: 'La distribution du doute', limit: 20 });
    evidenceSection(host, 'fragile_atoms_total', { title: 'Les souvenirs fragiles', limit: 60 });
    evidenceSection(host, 'decisions_without_rationale', { title: 'Les décisions sans pourquoi', limit: 30 });
    evidenceSection(host, 'incomplete_scopes_total', { title: 'Les territoires trop maigres', limit: 40 });
    evidenceSection(host, 'never_recalled_scopes_total', { title: 'Les territoires jamais relus', limit: 40 });
    evidenceSection(host, 'least_confident_project', { title: 'Les projets à consolider', limit: 20 });
    evidenceSection(host, 'semantic_duplicates', { title: 'Les jumeaux sémantiques', limit: 40 });

    host.appendChild(el('div', { class: 'hr' }));
    host.appendChild(el('p', { class: 'lede small', text: 'Les deux mesures suivantes ne valent pas zéro : elles n\'ont jamais été alimentées. Aucun agent n\'écrit last_verified_at ni confirmed_until — une couverture de 0 % se lirait comme un défaut du savoir alors que c\'est une absence de mécanisme.' }));
    evidenceSection(host, 'confidence_verification_coverage', {
      title: 'La relecture du savoir', naTitle: 'Mécanisme non alimenté', limit: 10 });
    evidenceSection(host, 'confidence_expiry_horizon', {
      title: 'La péremption du savoir', naTitle: 'Mécanisme non alimenté', limit: 10 });
  }

  /* =======================================================================
     12nonies · « CHRONOLOGIE » — rejouer une journée du cerveau
     ======================================================================= */

  var DAY_MS = 86400000;

  function isoAt(t) { return new Date(t).toISOString(); }
  function startOfLocalDay(t) { var d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); }

  /* Les bornes d'une plage sont la QUESTION posée au moteur, pas une mesure du
     cerveau : les calculer ici ne produit aucune valeur affichée. */
  function timelinePresets() {
    var now = Date.now(), today = startOfLocalDay(now);
    return [
      { id: 'aujourdhui', label: 'aujourd\'hui', from: isoAt(today), to: isoAt(now), g: 'hour' },
      { id: 'hier', label: 'hier', from: isoAt(today - DAY_MS), to: isoAt(today), g: 'hour' },
      { id: '7j', label: '7 jours', from: isoAt(today - DAY_MS * 6), to: isoAt(now), g: 'day' },
      { id: '30j', label: '30 jours', from: isoAt(today - DAY_MS * 29), to: isoAt(now), g: 'day' }
    ];
  }

  function localInput(iso) {
    var t = ms(iso);
    if (t === null) return '';
    var d = new Date(t - d0offset(t));
    return d.toISOString().slice(0, 16);
  }
  function d0offset(t) { return new Date(t).getTimezoneOffset() * 60000; }
  function inputToIso(v) { var t = Date.parse(v); return isFinite(t) ? isoAt(t) : null; }

  /* La bande temporelle : une piste par série servie, chacune à son échelle.
     Les hauteurs sont des pixels ; aucune valeur n'est dérivée ni affichée. */
  function timelineBand(buckets, onPick) {
    var keys = [];
    if (buckets.length) {
      for (var k in buckets[0]) {
        if (!hasOwn(buckets[0], k) || k === 'at') continue;
        if (typeof buckets[0][k] === 'number') keys.push(k);
      }
    }
    var wrap = el('div', { class: 'stack' });
    keys.forEach(function (key) {
      var W = 1000, H = 44;
      var root = svgBox('0 0 ' + W + ' ' + H, 'band', 'piste ' + key, true);
      var nb = buckets.length || 1;
      var step = W / nb;
      var hi = 0;
      buckets.forEach(function (b) { if (typeof b[key] === 'number' && b[key] > hi) hi = b[key]; });
      root.appendChild(sv(root, 'line', { x1: 0, y1: H - 1, x2: W, y2: H - 1, class: 'spark-axis' }));
      buckets.forEach(function (b, i) {
        var v = b[key];
        var cell = sv(root, 'rect', { x: i * step, y: 0, width: step, height: H, class: 'band-hit' });
        svTitle(root, cell, fmtStamp(b.at) + ' — ' + key + ' ' + fmtNum(v));
        if (onPick) cell.addEventListener('click', function () { onPick(i); });
        root.appendChild(cell);
        if (typeof v !== 'number' || v <= 0 || hi <= 0) return;
        var h = (H - 4) * v / hi;
        root.appendChild(sv(root, 'rect', {
          x: i * step, y: H - 1 - h, width: Math.max(step - 1, 0.6), height: h, class: 'band-bar'
        }));
      });
      wrap.appendChild(el('div', { class: 'band-row' }, [
        el('span', { class: 'band-name mono tiny', text: key }),
        el('div', { class: 'band-plot' }, root)
      ]));
    });
    if (!keys.length) wrap.appendChild(emptyBlock('Aucune série servie', 'le moteur n\'a produit aucun seau pour cette plage.'));
    else wrap.appendChild(el('p', { class: 'tiny faint', text: 'chaque piste porte SON échelle : les hauteurs se comparent dans le temps, jamais d\'une piste à l\'autre. Un clic sur une colonne recadre la plage sur ce seau.' }));
    return wrap;
  }

  function viewChronologie(host, q) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de la chronologie…' }));
    host.appendChild(box);
    var params = {
      from: q.from || '', to: q.to || '',
      granularity: q.granularity || 'hour', types: q.types || ''
    };
    get(API + '/timeline' + qs(params)).then(function (r) {
      clear(box);
      if (!r.ok) { box.appendChild(naBlock({ title: 'La chronologie n\'a pas pu être lue', reason: r.reason })); return; }
      var d = r.data || {};
      if (d.state === 'unavailable') { box.appendChild(naBlock({ title: 'Chronologie indisponible', reason: d.reason })); return; }
      var range = d.range || {};

      /* --- LE SÉLECTEUR --- */
      var tools = el('div', { class: 'toolbar' });
      tools.appendChild(el('span', { class: 'eyebrow', text: 'plage' }));
      timelinePresets().forEach(function (p) {
        var b = el('button', { class: 'pill', type: 'button', text: p.label,
          'aria-pressed': (q.from === p.from && q.to === p.to) ? 'true' : 'false' });
        b.addEventListener('click', function () { navPatch({ from: p.from, to: p.to, granularity: p.g }); });
        tools.appendChild(b);
      });

      var fromIn = el('input', { type: 'datetime-local', value: localInput(range.from), 'aria-label': 'début de la plage' });
      var toIn = el('input', { type: 'datetime-local', value: localInput(range.to), 'aria-label': 'fin de la plage' });
      var apply = el('button', { class: 'pill', type: 'button', text: 'appliquer la plage' });
      apply.addEventListener('click', function () {
        var f = inputToIso(fromIn.value), t = inputToIso(toIn.value);
        if (f && t) navPatch({ from: f, to: t });
      });
      tools.appendChild(el('div', { class: 'field' }, [el('label', { text: 'du' }), fromIn]));
      tools.appendChild(el('div', { class: 'field' }, [el('label', { text: 'au' }), toIn]));
      tools.appendChild(apply);

      var grans = d.granularities || {};
      var gopts = [];
      for (var gk in grans) { if (hasOwn(grans, gk)) gopts.push([gk, grans[gk]]); }
      tools.appendChild(selectField({ granularity: range.granularity }, 'granularity', gopts, 'granularité'));
      var sqlBtn = registerSqlEvidence('timeline', d.evidence);
      if (sqlBtn) tools.appendChild(sqlBtn);
      box.appendChild(tools);

      box.appendChild(el('p', { class: 'tiny faint mono', text: fmtStamp(range.from) + ' → ' + fmtStamp(range.to) +
        ' · ' + (range.granularity_label || range.granularity) + ' · pas ' + (range.step || '—') }));

      (d.notices || []).forEach(function (n) {
        box.appendChild(el('p', { class: 'tiny', text: '◇ ' + (typeof n === 'string' ? n : JSON.stringify(n)) }));
      });

      /* --- LES TYPES D'ÉVÉNEMENT --- */
      var types = d.types || {};
      var selected = types.selected || [];
      var tw = el('div', { class: 'toolbar' });
      tw.appendChild(el('span', { class: 'eyebrow', text: 'types' }));
      (types.available || []).forEach(function (t) {
        var on = selected.indexOf(t) >= 0;
        var b = el('button', { class: 'pill', type: 'button', text: t, 'aria-pressed': on ? 'true' : 'false' });
        b.addEventListener('click', function () {
          var next = [];
          (types.available || []).forEach(function (x) {
            var keep = selected.indexOf(x) >= 0;
            if (x === t) keep = !keep;
            if (keep) next.push(x);
          });
          navPatch({ types: next.join(',') });
        });
        tw.appendChild(b);
      });
      box.appendChild(tw);

      /* --- LA BANDE --- */
      var buckets = d.buckets || [];
      box.appendChild(section('La bande temporelle',
        el('span', { class: 'tiny faint', text: (d.buckets_truncated && d.buckets_truncated.applied) ? 'seaux tronqués par le moteur' : '' }),
        buckets.length ? timelineBand(buckets, function (i) {
          var b0 = buckets[i], b1 = buckets[i + 1];
          navPatch({ from: b0.at, to: b1 ? b1.at : range.to });
        }) : emptyBlock('Aucun seau', 'la plage demandée ne produit aucun intervalle.')));

      /* --- LE FLUX DE LA PÉRIODE --- */
      var events = d.events || [];
      box.appendChild(section('Ce qui s\'est passé, dans l\'ordre',
        el('span', { class: 'tiny faint', text: d.events_note || '' }),
        events.length ? el('div', { class: 'stack' }, [
          dataTable([
            { label: 'quand', nowrap: true, cell: function (e) { return el('span', { class: 'ts', text: fmtStamp(e.at) }); } },
            { label: 'il y a', nowrap: true, cell: function (e) { return fmtRel(e.at); } },
            /* Une destination servie doit toujours avoir une issue. Quand le moteur
               pointe une MÉTRIQUE (rappel, cycle), la ligne n'est pas navigable —
               le tiroir de preuve n'est pas une route — mais le type devient un
               bouton qui l'ouvre. Sans cela, 83 % des lignes de ce tableau
               portaient une destination sans aucun moyen de l'atteindre. */
            { label: 'type', nowrap: true, cell: function (e) {
                var mk = metricKeyFromHref(e.href);
                if (!mk) return el('span', { class: 'chip', text: e.type });
                var mm = metric(mk);
                return el('button', {
                  class: 'pill', type: 'button', 'data-metric': mk,
                  title: (mm ? mm.label + '\n\n' + mm.definition : mk) + '\n\nun clic ouvre la preuve de cette mesure',
                  text: e.type + ' ↗'
                });
              } },
            { label: 'sujet', cls: 't1', wrap: true, cell: function (e) {
                return el('span', {}, [
                  el('div', { text: e.subject_label || '—' }),
                  el('div', { class: 'card-key', text: (e.subject_kind || '') + (e.subject_id ? ' · ' + e.subject_id : '') })
                ]);
              } },
            { label: 'ce que le moteur en dit', wrap: true, cell: function (e) {
                var m2 = e.measures || {}, bits = [];
                for (var k2 in m2) { if (hasOwn(m2, k2)) bits.push(el('span', { class: 'measure' }, [
                  el('span', { class: 'k', text: k2 }), el('span', { class: 'v', text: fmtCell(m2[k2]) })])); }
                return bits.length ? el('span', { class: 'measures' }, bits) : el('span', { class: 'faint', text: '—' });
              } }
          ], events, { href: function (e) { return hrefToHash(e.href); } }),
          (d.events_truncated && d.events_truncated.applied)
            ? el('p', { class: 'tiny faint', text: 'flux tronqué par le moteur à ' + fmtNum(d.events_truncated.limit) + ' événements.' }) : null
        ]) : emptyBlock('Aucun événement sur cette plage',
          'le cerveau travaille quelques fois par jour : une plage sans événement est un repos observé, pas une panne.')));

      if (d.links && d.links.state === 'unavailable') {
        box.appendChild(section('Ce que cette chronologie ne peut pas montrer', null, naBlock({
          title: 'Les liens entre atomes', reason: d.links.reason, gesture: d.links.gesture,
          substitute: d.links.substitute, source: 'arac.atom_links'
        })));
      }
    });
  }

  /* =======================================================================
     13 · CHAMPS DE FILTRE — la question posée au cerveau
     ======================================================================= */

  function searchField(q, key, label) {
    var input = el('input', { type: 'search', value: q[key] || '', 'aria-label': label });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { var n = {}; n[key] = input.value; n.offset = 0; navPatch(n); }
    });
    return el('div', { class: 'field' }, [el('label', { text: label }), input]);
  }

  function selectField(q, key, options, label) {
    var sel = el('select', { 'aria-label': label });
    sel.appendChild(el('option', { value: '', text: '—' }));
    options.forEach(function (o) {
      var opt = el('option', { value: o[0], text: o[1] });
      if (String(q[key] || '') === String(o[0])) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener('change', function () { var n = {}; n[key] = sel.value; n.offset = 0; navPatch(n); });
    return el('div', { class: 'field' }, [el('label', { text: label }), sel]);
  }

  function pillGroup(q, key, facet, allLabel) {
    var wrap = el('div', { class: 'toolbar', style: 'gap:6px;margin:0' });
    var all = el('button', { class: 'pill', type: 'button', text: allLabel, 'aria-pressed': q[key] ? 'false' : 'true' });
    all.addEventListener('click', function () { var n = {}; n[key] = ''; n.offset = 0; navPatch(n); });
    wrap.appendChild(all);
    if (facet) {
      var keys = Object.keys(facet).filter(function (k) { return k !== 'note'; });
      keys.sort(function (a, b) { return facet[b] - facet[a]; });
      keys.forEach(function (k) {
        var b = el('button', {
          class: 'pill', type: 'button', 'aria-pressed': String(q[key] || '') === k ? 'true' : 'false',
          text: k + ' ' + fmtNum(facet[k])
        });
        b.addEventListener('click', function () { var n = {}; n[key] = k; n.offset = 0; navPatch(n); });
        wrap.appendChild(b);
      });
    }
    return wrap;
  }

  function pager(q, d) {
    var limit = d.limit, offset = d.offset;
    var wrap = el('div', { class: 'pager' });
    var prev = el('button', { class: 'pill', type: 'button', text: '← précédent' });
    var next = el('button', { class: 'pill', type: 'button', text: 'suivant →' });
    /* CE QUI ÉTAIT FAUX : la borne basse était gardée (`prev.disabled = !offset`),
       la haute ne l'était pas. À la dernière page, « suivant → » menait à un écran
       vide — un `<table>` sans corps, sans explication — sous une mention
       arithmétiquement absurde du genre « lignes 400…400 sur 365 ».
       CE QUE CETTE VERSION GARANTIT : la borne haute vient du total SERVI par le
       moteur, et la mention de plage n'est plus composée à la main quand la page
       est vide. Le total affiché reste, toujours, celui du moteur : le nombre de
       lignes reçues ne sert qu'à dire OÙ ON EST dans la liste — un fait sur l'écran,
       jamais une mesure du cerveau. */
    var shown = (d.items || []).length;
    var total = (typeof d.total === 'number') ? d.total : null;
    prev.disabled = !offset;
    next.disabled = (total !== null) ? (offset + shown >= total) : !shown;
    prev.addEventListener('click', function () { navPatch({ offset: Math.max(0, offset - limit) }); });
    next.addEventListener('click', function () { navPatch({ offset: offset + limit }); });
    wrap.appendChild(prev);
    wrap.appendChild(el('span', { class: 'tiny faint mono', text: shown
      ? 'lignes ' + fmtNum(offset + 1) + '…' + fmtNum(offset + shown) + ' sur ' + fmtNum(d.total)
      : 'aucune ligne à cet emplacement — la liste en compte ' + fmtNum(d.total) }));
    wrap.appendChild(next);
    return wrap;
  }

  /* =======================================================================
     14 · FLUX D'ACTIVITÉ — SSE, repli JSON, aucune phrase inventée
     ======================================================================= */

  var MAX_SHOWN = 300;
  var es = null, pollTimer = null, sseRetryTimer = null, sseFailures = 0;

  function setMode(mode, why) {
    S.mode = mode;
    var live = $('#link-live');
    live.setAttribute('data-mode', mode);
    var word = mode === 'sse' ? 'flux direct' : mode === 'poll' ? 'repli json' : mode === 'down' ? 'flux coupé' : 'connexion';
    $('#link-word').textContent = word;
    live.title = (why || '') + (mode === 'poll'
      ? '\nLe flux SSE a échoué : le cockpit interroge /cc/v1/events. Mode dégradé, annoncé.'
      : '');
  }

  function composeEvent(ev) {
    var tpl = S.msgCatalog ? S.msgCatalog[ev.message_key] : null;
    if (!tpl) return { text: '[événement inconnu : ' + (ev.type || ev.message_key || '?') + ']', unknown: true };
    var args = ev.message_args || {};
    var out = tpl.replace(/\{(\w+)\}/g, function (whole, name) {
      var v = args[name];
      if (v === null || v === undefined) return '—';
      return typeof v === 'number' ? fmtNum(v) : String(v);
    });
    return { text: out, unknown: false };
  }

  function eventNode(ev) {
    var c = composeEvent(ev);
    var sub = ev.subject && ev.subject.label ? cut(ev.subject.label, 42) : (ev.stage || '');
    var node = el('div', {
      class: 'ev', 'data-level': ev.level || 'info', 'data-unknown': c.unknown ? '1' : '0',
      title: 'type ' + (ev.type || '?') + '\nfait à ' + fmtStamp(ev.ts) + '\nvu à ' + fmtStamp(ev.observed_at) + '\nid ' + (ev.event_id || '—')
    }, [
      el('span', { class: 'ev-ts', text: fmtClock(ev.ts) }),
      el('span', { class: 'ev-stage', text: ev.stage || '—' }),
      el('span', { class: 'ev-msg', text: c.text }),
      el('span', { class: 'ev-sub', text: sub })
    ]);
    return node;
  }

  function pushEvents(items) {
    if (!items || !items.length) return;
    var body = $('#flux-body');
    for (var i = 0; i < items.length; i++) {
      var ev = items[i];
      S.events.unshift(ev);
      S.lastEventId = ev.event_id || S.lastEventId;
      body.insertBefore(eventNode(ev), body.firstChild);
    }
    while (S.events.length > MAX_SHOWN) S.events.pop();
    while (body.childNodes.length > MAX_SHOWN) body.removeChild(body.lastChild);
    var last = S.events[0];
    if (last) {
      var c = composeEvent(last);
      $('#flux-last').textContent = fmtClock(last.ts) + ' · ' + c.text;
    }
    renderRest();
    /* Un fait nouveau : on relit les mesures. Aucun mouvement sans événement. */
    scheduleRefresh();
    scheduleViewRefresh(items);
  }

  /* LA GARDE ANTI-VOL DE FOCUS, en un seul endroit.
     CE QUI ÉTAIT FAUX : la garde n'existait qu'au minuteur des 30 secondes
     (voir `boot`), alors que les DEUX chemins les plus fréquents l'ignoraient —
     `scheduleRefresh()`, déclenché par chaque salve d'événements SSE, et
     `refreshStreamState()`, armé toutes les 60 s. `renderVitals()` détruit les cinq
     tuiles du bandeau : si le clavier en tenait une, le focus tombait sur le corps
     du document, exactement ce que la garde des 30 s dit vouloir empêcher.
     CE QUE CETTE VERSION GARANTIT : un seul point de passage. Le seul appel direct
     restant est celui de `reloadAll()`, qui répond à un geste explicite (touche « r »)
     — là, le lecteur a demandé la relecture, on la lui donne. */
  function renderVitalsSafely() {
    var strip = $('#vital-strip');
    if (strip && strip.contains(document.activeElement)) return;
    renderVitals();
  }

  var refreshTimer = null;
  function scheduleRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(function () {
      refreshTimer = null;
      loadMetrics().then(function () { renderVitalsSafely(); });
    }, 3000);
  }

  /* -----------------------------------------------------------------------
     LES VUES QUI VIVENT — un écran se relit quand un fait le CONCERNE.
     Pas de sondage, pas de rechargement complet, pas d'horloge : le flux SSE
     est déjà ouvert, et c'est lui qui décide. Un écran dont aucun étage n'a
     bougé ne bouge pas non plus — c'est ce qui rend le mouvement lisible.

     Les étages sont ceux que le catalogue du flux publie (`stage`) : capture,
     import, analyse, atomes, rappel, systeme.
     ----------------------------------------------------------------------- */
  var LIVE_STAGES = {
    aujourdhui:    ['capture', 'import', 'analyse', 'atomes', 'rappel'],
    chronologie:   ['capture', 'import', 'analyse', 'atomes', 'rappel'],
    atomes:        ['atomes', 'analyse'],
    scopes:        ['atomes', 'analyse'],
    projets:       ['atomes', 'analyse'],
    confiance:     ['atomes', 'analyse'],
    conversations: ['capture', 'import', 'analyse'],
    general:       ['capture', 'import', 'analyse', 'atomes', 'rappel'],
    activite:      ['capture', 'import', 'analyse', 'atomes', 'rappel', 'systeme'],
    digestion:     ['analyse', 'atomes'],
    memoire:       ['atomes'],
    rappel:        ['rappel'],
    croissance:    ['atomes'],
    pipeline:      ['capture', 'import', 'analyse']
  };

  var viewRefreshTimer = null;

  function scheduleViewRefresh(items) {
    var head = (S.route && S.route.seg && S.route.seg[0]) || 'aujourdhui';
    /* Un écran qui a posé son crochet reçoit les faits BRUTS et se met à jour
       lui-même, à sa granularité. On ne le redessine pas par-dessus : une vue
       qui sait s'amender vaut mieux qu'une vue qu'on jette. */
    if (S.liveHook && S.liveHook.view === head) { S.liveHook.onEvents(items); return; }
    if (!hasOwn(LIVE_STAGES, head)) return;
    var stages = LIVE_STAGES[head], concerned = false;
    for (var i = 0; i < items.length; i++) {
      if (stages.indexOf(items[i].stage) >= 0) concerned = true;
    }
    if (!concerned) return;
    if (viewRefreshTimer) return;
    viewRefreshTimer = setTimeout(function () {
      viewRefreshTimer = null;
      /* On ne redessine JAMAIS sous les doigts du lecteur : ni pendant qu'une
         preuve est ouverte, ni pendant qu'il tape dans un champ. Le fait reste
         acquis — l'écran se remettra à jour au prochain geste de navigation. */
      if (drawer && drawer.getAttribute('data-open') === '1') return;
      var tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      /* CE QUI ÉTAIT FAUX : cette garde ne vérifiait que le tiroir et la saisie.
         `render()` remet `#view.scrollTop` à 0 et reconstruit l'écran : le lecteur
         qui lisait le bas d'« Aujourd'hui » était ramené en tête sans l'avoir demandé,
         et tous les replis ouverts se refermaient. La vue « cascade », elle, teste
         déjà la position de lecture (`quiet()`).
         CE QUE CETTE VERSION GARANTIT : on ne redessine que si l'écran est resté en
         tête. Ailleurs, on ne bouge rien — le fait reste acquis, l'écran se relira
         au prochain geste de navigation, ce que la phrase ci-dessus promet déjà. */
      var viewHost = $('#view');
      if (viewHost && viewHost.scrollTop > 4) return;
      render();
      markLive();
    }, 4000);
  }

  /* La trace de la mise à jour : ambre, parce que c'est la machine qui
     s'enregistre — jamais une alarme, jamais un mouvement gratuit. */
  function markLive() {
    var host = $('#view');
    if (!host) return;
    var mark = el('div', { class: 'live-mark', role: 'status' },
      el('span', { text: 'écran relu sur un fait observé · ' + fmtClock(new Date().toISOString()) }));
    host.insertBefore(mark, host.firstChild);
    setTimeout(function () { if (mark.parentNode) mark.parentNode.removeChild(mark); }, 12000);
  }

  function connectSSE() {
    if (!window.EventSource) { startPolling('EventSource absent de ce navigateur'); return; }
    var name = (S.transport && S.transport.sse && S.transport.sse.event_name) || 'message';
    var url = API + '/stream' + (S.lastEventId ? '?since=' + encodeURIComponent(S.lastEventId) : '');
    try { es = new window.EventSource(url, { withCredentials: true }); }
    catch (e) { startPolling('ouverture du flux impossible'); return; }

    es.addEventListener('open', function () { sseFailures = 0; setMode('sse', 'flux SSE ouvert'); });
    es.addEventListener(name, function (m) {
      try { pushEvents([JSON.parse(m.data)]); } catch (e) { /* enveloppe illisible : ignorée, jamais devinée */ }
    });
    es.addEventListener('error', function () {
      sseFailures = sseFailures + 1;
      if (es && es.readyState === 2) {
        es = null;
        startPolling('flux SSE fermé par le serveur');
      } else if (sseFailures > 3) {
        try { es.close(); } catch (e) {}
        es = null;
        startPolling('flux SSE instable');
      } else {
        setMode('down', 'flux SSE interrompu — reconnexion');
      }
    });
  }

  function startPolling(why) {
    setMode('poll', why);
    if (pollTimer) return;
    var tick = function () {
      get(API + '/events' + qs({ since: S.lastEventId, limit: 200 })).then(function (r) {
        if (!r.ok) { setMode('down', r.reason); return; }
        setMode('poll', why);
        var d = r.data || {};
        if (d.items && d.items.length) pushEvents(d.items);
        else if (d.next_since) S.lastEventId = d.next_since;
      });
    };
    tick();
    pollTimer = setInterval(tick, 5000);
    if (!sseRetryTimer) {
      sseRetryTimer = setInterval(function () {
        if (S.mode !== 'poll' && S.mode !== 'down') return;
        get(API + '/stream/state').then(function (r) {
          if (!r.ok) return;
          clearInterval(pollTimer); pollTimer = null;
          clearInterval(sseRetryTimer); sseRetryTimer = null;
          sseFailures = 0;
          connectSSE();
        });
      }, 60000);
    }
  }

  function refreshStreamState() {
    return get(API + '/stream/state').then(function (r) {
      if (r.ok) { S.stream = r.data; renderVitalsSafely(); renderRest(); }
    });
  }

  function renderRest() {
    var st = S.stream;
    var host = $('#flux-rest');
    clear(host);
    if (!st) return;
    var next = st.next_cycle || {};
    var la = st.last_activity || {};
    var stamps = [];
    for (var k in la) {
      if (!Object.prototype.hasOwnProperty.call(la, k)) continue;
      var t = ms(la[k]);
      if (t !== null) stamps.push({ k: k, t: t, iso: la[k] });
    }
    stamps.sort(function (a, b) { return b.t - a.t; });
    host.appendChild(el('div', { class: 'tiny faint' }, [
      el('span', { text: st.idle ? 'Le cerveau est au repos. ' : 'Un passage est en cours. ' }),
      el('span', { text: stamps.length ? 'Dernier signe : ' + stamps[0].k + ' ' + fmtRel(stamps[0].iso) + '. ' : '' }),
      el('span', { text: next.at_utc ? 'Prochain cycle ' + fmtRel(next.at_utc) + ' (créneau ' + (next.slot || '?') + ').' : '' })
    ]));
    if (!S.events.length) {
      host.appendChild(el('div', { class: 'tiny faint', text: 'Aucun événement depuis l\'ouverture de cette page. C\'est le comportement correct : ce cockpit n\'anime rien qu\'il n\'a pas observé.' }));
    }
  }

  /* =======================================================================
     14bis · « LE CERVEAU PENSE » — LA CASCADE
     -----------------------------------------------------------------------
     Le flux montre des faits ISOLÉS. Cet écran montre l'ENCHAÎNEMENT : le
     trajet d'UNE conversation dans UN cycle, de la détection à la mémoire
     consolidée. Onze étapes, servies dans l'ordre du pipeline par
     /cc/v1/cascade.

     Trois règles tiennent cette vue :

     1. AUCUNE PHRASE N'EST ÉCRITE ICI. Le serveur désigne un `template_key`
        et fournit ses `args` ; les gabarits arrivent avec la réponse. Une clé
        inconnue s'affiche « [étape inconnue : clé] » — jamais un texte deviné.

     2. UNE ÉTAPE `unavailable` RESTE VISIBLE. Teinte neutre, marque ◇, raison,
        geste, substitut. La masquer laisserait croire que la mesure vaut zéro ;
        elle n'a jamais été prise.

     3. LE CONNECTEUR EST DU CSS. Aucun caractère │ ├ └ n'est écrit : le trait
        vertical et la patte horizontale sont des bordures et des
        pseudo-éléments (cf. `.casc-rail` dans ds.css). Un dessin fait de
        caractères se lirait à voix haute par un lecteur d'écran.
     ======================================================================= */

  /* La marque d'état d'une étape : TYPOGRAPHIQUE d'abord, colorée ensuite.
     Aucun état de ce cockpit ne tient à la seule teinte — le mot d'état est
     servi au lecteur d'écran, et la marque reste lisible en noir et blanc. */
  var STEP_MARK = { passed: '·', failed: '■', skipped: '–', unavailable: '◇' };
  var STEP_WORD = {
    passed: 'étape franchie',
    failed: 'étape échouée',
    skipped: 'étape sans objet',
    unavailable: 'étape jamais mesurée'
  };

  /* Les clés de `measures` qui décrivent une ABSENCE. Elles remontent dans un
     bloc d'absence au lieu d'être noyées au milieu des mesures : une absence
     doit se lire, pas se déchiffrer. */
  var NA_MEASURE_KEYS = { state: 1, reason: 1, gesture: 1, substitute: 1, impact: 1 };

  /* Rendre une durée servie en millisecondes. Le catalogue de la cascade le
     demande explicitement (`arg_formats._ms`) : « 97004 » et « 1 min 37 s »
     sont la même donnée. Changer d'unité est du formatage, pas de l'agrégation. */
  function fmtDuration(v) {
    if (typeof v !== 'number' || !isFinite(v)) return fmtNum(v);
    var s = v / 1000;
    if (s < 1) return NF.format(v) + ' ms';
    if (s < 60) return NF.format(Math.round(s * 10) / 10) + ' s';
    var mn = Math.floor(s / 60);
    if (mn < 60) return mn + ' min ' + Math.round(s - mn * 60) + ' s';
    var h = Math.floor(mn / 60);
    return h + ' h ' + (mn - h * 60) + ' min';
  }

  /* Le suffixe de l'argument dit comment le rendre — c'est le contrat publié
     par /cc/v1/cascade/catalog (`arg_formats`). Le client met en forme ; il ne
     décide de rien. */
  function fmtStepArg(name, v) {
    if (v === null || v === undefined) return '—';
    if (/_ms$/.test(name)) return fmtDuration(v);
    if (/_at$/.test(name) && typeof v === 'string') return fmtStamp(v);
    if (Array.isArray(v)) return v.join(' · ');
    return typeof v === 'number' ? fmtNum(v) : String(v);
  }

  /* Comme `composeSentence`, mais en honorant les formats d'argument servis.
     Le gabarit reste celui du moteur ; seul le rendu des valeurs change. */
  function composeStep(step, templates, unknownTpl) {
    var tpl = (templates && step && hasOwn(templates, step.template_key)) ? templates[step.template_key] : null;
    if (typeof tpl !== 'string') {
      var fallback = unknownTpl || '[étape inconnue : {key}]';
      return { text: fallback.replace(/\{key\}/g, (step && step.template_key) || '?'), unknown: true };
    }
    var args = (step && step.args) || {};
    var out = tpl.replace(/\{(\w+)\}/g, function (whole, name) {
      if (!hasOwn(args, name)) return whole;
      return fmtStepArg(name, args[name]);
    });
    return { text: out, unknown: false };
  }

  /* Les mesures d'une étape, telles qu'elles arrivent. Aucune n'est recalculée :
     ce bloc est un miroir de `measures`, pas un tableau de bord. */
  function measureList(obj) {
    var rows = [];
    for (var k in obj) {
      if (!hasOwn(obj, k) || hasOwn(NA_MEASURE_KEYS, k)) continue;
      var v = obj[k];
      if (v === undefined) continue;
      rows.push(el('span', { class: 'measure' }, [
        el('span', { class: 'k', text: k }),
        el('span', { class: 'v', text: Array.isArray(v) ? (v.length ? v.join(' · ') : '—') : fmtCell(v) })
      ]));
    }
    return rows.length ? el('div', { class: 'measures' }, rows) : null;
  }

  /* La route d'écran d'une cible. Un chemin qu'aucun écran ne sert ne produit
     AUCUN lien : on ne devine pas une destination. */
  function targetHash(t) {
    if (!t || !t.href) return null;
    var direct = hrefToHash(t.href);
    if (direct) return direct;
    var tl = API + '/timeline?';
    if (t.href.indexOf(tl) === 0) return '#/chronologie?' + t.href.slice(tl.length);
    var rp = API + '/replay?';
    if (t.href.indexOf(rp) === 0) return '#/rejeu?' + t.href.slice(rp.length);
    return null;
  }

  /* Une source qui pointe une preuve de métrique ouvre le tiroir du registre :
     c'est le chemin déjà servi par le cockpit, pas un second chemin parallèle. */
  function evidenceKeyOf(href) {
    var m = /^\/cc\/v1\/evidence\/([^?]+)/.exec(href || '');
    return m ? decodeURIComponent(m[1]) : null;
  }

  /* Une source, rendue selon ce vers quoi elle mène. Une source qui ne mène
     nulle part reste AFFICHÉE et marquée : un lien mort est pire qu'un lien
     absent, mais une source tue est pire que les deux. */
  function sourceChip(s) {
    var key = evidenceKeyOf(s.href);
    if (key) return el('button', { class: 'pill', type: 'button', 'data-metric': key, text: '↗ ' + cut(s.label || key, 34) });
    var hash = targetHash(s);
    if (hash) return el('button', { class: 'pill', type: 'button', 'data-go': hash, text: '→ ' + cut(s.label || s.ref || s.kind, 34) });
    return el('span', { class: 'chip', 'data-state': 'unavailable', title: s.href || '' },
      [glyph('unavailable'), el('span', { text: cut(s.label || s.ref || s.kind || '?', 34) })]);
  }

  /* Une cible cliquable. Sans écran d'arrivée, elle reste AFFICHÉE mais inerte,
     et dit pourquoi — un lien mort est pire qu'un lien absent. */
  function targetChip(t) {
    var label = t.label || t.ref || t.kind || '?';
    var hash = targetHash(t);
    var extra = [];
    if (t.atomes_du_trajet !== undefined && t.atomes_du_trajet !== null) extra.push(fmtNum(t.atomes_du_trajet) + ' atome(s) ici');
    if (t.atomes !== undefined && t.atomes !== null) extra.push(fmtNum(t.atomes) + ' atome(s)');
    if (t.racine_nue) extra.push('racine nue');
    if (t.status) extra.push(String(t.status));
    if (t.motif) extra.push('motif : ' + t.motif);
    if (t.survie_jours !== undefined && t.survie_jours !== null) extra.push('survie ' + fmtNum(t.survie_jours) + ' j');
    var title = (t.kind || '?') + ' · ' + (t.ref === null || t.ref === undefined ? '—' : String(t.ref))
      + (extra.length ? '\n' + extra.join('\n') : '')
      + (t.rule ? '\nrègle : ' + t.rule : '');
    if (hash) {
      return el('button', { class: 'casc-target', type: 'button', 'data-go': hash, 'data-kind': t.kind || 'autre', title: title }, [
        el('span', { class: 'casc-target-kind', text: t.kind || '?' }),
        el('span', { text: cut(label, 46) })
      ]);
    }
    return el('span', { class: 'casc-target', 'data-kind': t.kind || 'autre', 'data-dead': '1', title: title }, [
      el('span', { class: 'casc-target-kind', text: t.kind || '?' }),
      el('span', { text: cut(label, 46) }),
      el('span', { class: 'card-key', text: 'sans écran dédié' })
    ]);
  }

  /* Les sources d'une étape. Celles qui portent un SQL ouvrent le tiroir de
     preuve : la requête est rejouable telle quelle dans un terminal, donc
     opposable. Les autres mènent à leur écran. */
  function stepSourceNodes(step, cid) {
    var srcs = step.sources || [];
    if (!srcs.length) return [el('span', { class: 'tiny faint', text: 'aucune source servie — cette étape n\'aurait pas dû être construite' })];
    var out = [];
    srcs.forEach(function (s, i) {
      if (s.sql) {
        var id = 'casc:' + cid + ':' + step.stage + ':' + i;
        out.push(registerSqlEvidence(id, {
          label: (step.stage_label || step.stage) + ' — ' + (s.label || s.ref || 'la trace'),
          sql: s.sql
        }));
        return;
      }
      out.push(sourceChip(s));
    });
    return out;
  }

  /* UNE ÉTAPE. Le connecteur est dessiné par ds.css ; ici on ne pose que la
     marque d'état, la phrase composée, les cibles et le repli des preuves. */
  function cascadeStepNode(step, cascade, templates, unknownTpl) {
    var state = step.state || 'passed';
    var c = composeStep(step, templates, unknownTpl);
    var cid = cascade.cascade_id;

    var detail = el('div', { class: 'casc-detail' });
    detail.hidden = true;

    var na = step.measures || {};
    if (state === 'unavailable' || na.reason) {
      detail.appendChild(naBlock({
        title: step.stage_label || step.stage,
        reason: na.reason || null,
        gesture: na.gesture || null,
        substitute: na.substitute || null,
        impact: na.impact || null
      }));
    }
    detail.appendChild(el('div', { class: 'tiny faint', text: step.rule ? 'règle d\'émission servie : ' + step.rule : 'aucune règle servie pour cette étape' }));
    var mes = measureList(step.measures || {});
    if (mes) detail.appendChild(mes);
    detail.appendChild(el('div', { class: 'toolbar' }, stepSourceNodes(step, cid)));

    var say = el('button', {
      class: 'casc-say', type: 'button', 'aria-expanded': 'false',
      'data-unknown': c.unknown ? '1' : '0',
      title: 'gabarit servi : ' + (step.template_key || '?') + '\n\nun clic ouvre sa règle, ses mesures et ses preuves'
    }, el('span', { class: 'casc-say-text', text: c.text }));
    say.addEventListener('click', function () {
      var open = detail.hidden;
      detail.hidden = !open;
      say.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    var targets = step.targets || [];
    var head = el('div', { class: 'casc-row' }, [
      el('span', { class: 'casc-stage', text: step.stage_label || step.stage }),
      targets.length ? el('span', { class: 'casc-targets' }, targets.map(targetChip)) : null
    ]);

    return el('li', { class: 'casc-step', 'data-state': state }, [
      el('span', { class: 'casc-at mono', text: step.at ? fmtClock(step.at) : '' }),
      el('span', { class: 'casc-rail', 'aria-hidden': 'true' },
        el('i', { class: 'casc-dot', 'data-state': state, text: STEP_MARK[state] || STEP_MARK.unavailable })),
      el('div', { class: 'casc-cell' }, [
        el('span', { class: 'sr-only', text: STEP_WORD[state] || STEP_WORD.unavailable }),
        head,
        say,
        step.duration_ms === null || step.duration_ms === undefined
          ? null
          : el('span', { class: 'casc-dur mono', text: fmtDuration(step.duration_ms) }),
        detail
      ])
    ]);
  }

  var OUTCOME_TONE = { learned: 'ok', no_new_knowledge: 'warn', failed: 'critical' };
  var OUTCOME_WORD = {
    learned: 'le cerveau a retenu quelque chose',
    no_new_knowledge: 'rien de neuf n\'a été retenu',
    failed: 'le passage n\'a pas abouti'
  };

  /* UNE CASCADE ENTIÈRE. Rien n'est compté ici : le sujet, le cycle et le
     verdict sont servis tels quels par /cc/v1/cascade. */
  function cascadeNode(item, templates, unknownTpl, isolated) {
    var subj = item.subject || {};
    var run = item.run || {};
    var out = item.outcome || {};

    var meta = [];
    if (subj.source_type) meta.push(String(subj.source_type));
    if (subj.messages !== null && subj.messages !== undefined) meta.push(fmtNum(subj.messages) + ' messages');
    if (subj.node_id) meta.push(String(subj.node_id));

    var subjectBtn = el('button', {
      class: 'casc-subject', type: 'button',
      'data-go': '#/conversations/' + encodeURIComponent(subj.uid || ''),
      title: 'ouvrir la conversation ' + (subj.uid || '?')
    }, [
      el('span', { class: 'casc-time mono', text: fmtClock(item.started_at) }),
      el('span', { class: 'casc-title', text: subj.title || '(sans titre)' }),
      el('span', { class: 'casc-meta', text: meta.join(' · ') })
    ]);

    /* Depuis la LISTE, isoler un trajet. Deuxième entrée vers `#/cascade/<uid>`,
       qui n'en avait aucune. Le sujet ouvre la conversation ; ceci ouvre son trajet. */
    var aloneBtn = (subj.uid && !isolated) ? el('button', {
      class: 'pill', type: 'button',
      'data-go': '#/cascade/' + encodeURIComponent(subj.uid),
      title: 'n\'afficher que ce trajet', text: '↗ ce trajet seul'
    }) : null;

    var runBits = [];
    if (run.ref) {
      var runHash = targetHash({ kind: 'run', href: API + '/timeline?granularity=hour' + (run.started_at ? '&from=' + encodeURIComponent(run.started_at) : '') + (run.ended_at ? '&to=' + encodeURIComponent(run.ended_at) : '') });
      runBits.push(el('button', { class: 'pill', type: 'button', 'data-go': runHash, text: '↗ cycle ' + run.ref }));
    }
    if (run.model) runBits.push(el('span', { class: 'tiny faint mono', text: String(run.model) }));
    if (run.duration_ms !== null && run.duration_ms !== undefined) runBits.push(el('span', { class: 'tiny faint mono', text: fmtDuration(run.duration_ms) }));

    var steps = el('ol', { class: 'casc-steps' },
      (item.steps || []).map(function (s) { return cascadeStepNode(s, item, templates, unknownTpl); }));

    var foot = [];
    if ((item.refused_without_source || []).length) {
      foot.push(el('p', { class: 'tiny faint', text: 'étapes refusées faute de source résolvable : '
        + item.refused_without_source.map(function (r) { return r.stage + ' (' + r.template_key + ')'; }).join(' · ') }));
    }
    var tr = item.truncated || {};
    if (tr.atoms) {
      foot.push(el('p', { class: 'tiny faint', text: 'le détail des atomes est tronqué à la borne servie ('
        + fmtNum(tr.atoms_limit) + ') — le compte affiché, lui, reste celui du moteur.' }));
    }

    /* DÉFAUT DE MÊME CLASSE QUE L'ENTONNOIR, trouvé en relisant ce fichier :
       `out.state || 'learned'` faisait d'un verdict NON SERVI un liseré VERT
       (ds.css : `[data-outcome="learned"]` = --ok, « le cerveau a retenu quelque
       chose ») — alors que, deux lignes plus bas, la pastille d'état disait
       correctement « verdict inconnu ». Le cadre et la pastille se contredisaient.
       Non reproduit sur les données du jour (les 5 cascades servies portent toutes
       un `state`) : c'est un défaut latent du repli, pas un pixel faux observé.
       `unknown` n'a pas de règle CSS : il retombe sur le liseré neutre — un verdict
       absent ne se peint pas en vert. */
    return el('article', {
      class: 'casc', 'data-outcome': out.state || 'unknown', 'data-cid': item.cascade_id
    }, [
      el('header', { class: 'casc-head' }, [
        subjectBtn,
        el('div', { class: 'casc-run' }, aloneBtn ? [aloneBtn].concat(runBits) : runBits),
        el('div', { class: 'casc-verdict' }, [
          stateChip(OUTCOME_TONE[out.state] || 'unavailable', OUTCOME_WORD[out.state] || String(out.state || 'verdict inconnu')),
          el('span', { class: 'tiny faint', text: fmtRel(item.started_at) })
        ])
      ]),
      steps,
      foot.length ? el('div', { class: 'casc-foot' }, foot) : null
    ]);
  }

  /* `uid` ouvre le trajet d'UNE conversation. Sans lui, le routeur calculait le
     sous-chemin puis l'oubliait : `#/cascade/<uid>` retombait sur la liste, et la
     seule vue qui montre un trajet réussi en entier restait inatteignable. */
  function viewCascade(host, uid) {
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin',
      text: uid ? 'reconstitution du trajet…' : 'reconstitution des trajets…' }));
    host.appendChild(box);

    get(API + '/cascade' + (uid ? '/' + encodeURIComponent(uid) : '')).then(function (r) {
      clear(box);
      /* La réponse peut arriver APRÈS que le lecteur a changé d'écran. On ne
         peuple pas un écran qu'il ne regarde plus, et surtout on n'y accroche
         pas de crochet sur le flux. */
      if (!box.isConnected) return;
      if (!r.ok) {
        box.appendChild(naBlock({
          title: 'Les cascades n\'ont pas pu être lues', reason: r.reason,
          gesture: 'vérifier la session du Control Center et l\'accès PostgreSQL en lecture seule',
          substitute: 'la chronologie (touche 2) reste servie par sa propre route'
        }));
        return;
      }
      var d = r.data || {};
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Cascades indisponibles', reason: d.reason, gesture: d.gesture, substitute: d.substitute }));
        return;
      }

      var templates = d.templates || null;
      var unknownTpl = d.unknown_template || null;

      box.appendChild(el('div', { class: 'toolbar' }, [
        el('span', { class: 'eyebrow', text: 'cascades achevées' }),
        el('span', { class: 'tiny faint mono', text: fmtNum(d.count) + ' servie(s) · borne ' + fmtNum(d.limit) }),
        registerSqlEvidence('cascade', d.evidence ? {
          label: 'Les requêtes qui reconstituent les trajets',
          sql: d.evidence.sql, queries: d.evidence.blocks
        } : null),
        el('span', { class: 'tiny faint', text: 'lignes lues : ' + fmtNum(d.rows_read) + ' / ' + fmtNum(d.rows_budget) })
      ]));

      if (d.doctrine) box.appendChild(el('p', { class: 'lede small', text: d.doctrine }));
      (d.notices || []).forEach(function (n) {
        box.appendChild(el('p', { class: 'tiny faint', text: n }));
      });

      /* La barre des nouvelles cascades. Elle ne bouge JAMAIS l'écran d'elle-même :
         si le lecteur n'est pas en haut, elle attend son clic. */
      var newBar = el('div', { class: 'casc-newbar' });
      newBar.hidden = true;
      var newBtn = el('button', { class: 'pill', type: 'button', text: '—' });
      newBar.appendChild(newBtn);
      box.appendChild(newBar);

      var list = el('div', { class: 'casc-list' });
      box.appendChild(list);

      var items = d.items || [];
      if (!items.length) {
        list.appendChild(emptyBlock('Aucune cascade achevée',
          d.reason || 'aucun cycle terminé ne porte de conversation dans son paquet.'));
      } else {
        items.forEach(function (it) { list.appendChild(cascadeNode(it, templates, unknownTpl, !!uid)); });
      }

      if ((d.refused_without_source || []).length) {
        box.appendChild(section('Ce que le serveur a refusé de raconter',
          el('span', { class: 'tiny faint', text: 'une étape sans source résolvable est refusée à la construction' }),
          el('div', { class: 'measures' }, d.refused_without_source.map(function (rf) {
            return el('span', { class: 'measure' }, [
              el('span', { class: 'k', text: rf.stage }),
              el('span', { class: 'v', text: rf.reason || '—' })
            ]);
          }))));
      }

      /* --- L'ARRIVÉE D'UNE CASCADE PAR SSE --------------------------------
         Un cycle qui se termine achève des cascades. Le flux le dit ; on relit
         alors /cc/v1/cascade et on INSÈRE en tête ce qui est nouveau. La vue
         n'est pas reconstruite : ni le focus clavier, ni la position de lecture,
         ni un repli ouvert ne sont perdus. */
      var seen = {};
      items.forEach(function (it) { seen[it.cascade_id] = 1; });
      var pending = [];
      var busy = false;
      var viewHost = $('#view');

      function quiet() {
        if (drawer && drawer.getAttribute('data-open') === '1') return false;
        if (list.contains(document.activeElement)) return false;
        if (newBar.contains(document.activeElement)) return false;
        return viewHost ? viewHost.scrollTop <= 4 : true;
      }

      function insert(nodes) {
        for (var i = nodes.length - 1; i >= 0; i--) {
          nodes[i].setAttribute('data-new', '1');
          list.insertBefore(nodes[i], list.firstChild);
        }
      }

      function showBar() {
        var howMany = pending.length;
        if (!howMany) { newBar.hidden = true; return; }
        newBtn.textContent = howMany > 1
          ? howMany + ' nouvelles cascades — afficher'
          : howMany + ' nouvelle cascade — afficher';
        newBar.hidden = false;
      }

      newBtn.addEventListener('click', function () {
        insert(pending);
        pending = [];
        showBar();
        if (viewHost) viewHost.scrollTop = 0;
      });

      function absorb(fresh) {
        if (!fresh.length) return;
        var nodes = fresh.map(function (it) { return cascadeNode(it, templates, unknownTpl); });
        if (quiet()) { insert(nodes); return; }
        pending = nodes.concat(pending);
        showBar();
      }

      /* CE QUI ÉTAIT FAUX : ce crochet relisait `/cc/v1/cascade` SANS l'identifiant,
         et `scheduleViewRefresh` l'applique aussi à `#/cascade/<uid>` (même premier
         segment). L'écran du trajet d'UNE conversation se remplissait donc des
         trajets des autres, insérés en tête — `seen` n'ayant été amorcé qu'avec
         l'unique item, toutes les autres cascades passaient pour fraîches.
         CE QUE CETTE VERSION GARANTIT : la vue détail n'arme aucun crochet. Un
         trajet achevé ne gagne pas de nouvelles étapes — il n'y a rien à y guetter.
         Seule la LISTE se met à jour, et elle relit bien la liste. */
      if (uid) return;

      S.liveHook = {
        view: 'cascade',
        onEvents: function (evs) {
          var concerned = false;
          for (var i = 0; i < evs.length; i++) if (evs[i].stage === 'analyse') concerned = true;
          if (!concerned || busy) return;
          busy = true;
          setTimeout(function () {
            get(API + '/cascade').then(function (r2) {
              busy = false;
              if (!r2.ok || !r2.data || !r2.data.items) return;
              var fresh = [];
              r2.data.items.forEach(function (it) {
                if (hasOwn(seen, it.cascade_id)) return;
                seen[it.cascade_id] = 1;
                fresh.push(it);
              });
              absorb(fresh);
            });
          }, 2000);
        }
      };
    });
  }

  /* =======================================================================
     14ter · LE LECTEUR DE REJEU — rejouer une journée du cerveau
     -----------------------------------------------------------------------
     Un lecteur, pas un tableau. Il PROJETTE ce que /cc/v1/replay a composé :

       · la cadence vient du serveur (`frame_ms`), pas d'une constante d'ici ;
       · les compteurs viennent de `frames[i].cumulative` — le client n'accumule
         RIEN, ne somme rien, ne soustrait rien. Il lit l'image et l'affiche ;
       · les vitesses offertes viennent de `speed.available` — changer de
         vitesse redemande le film au serveur, qui renvoie son `frame_ms` ;
       · une journée VIDE le dit (`empty.reason`) et reste rejouable dans la
         liste : un jour sans apprentissage est une information.

     `prefers-reduced-motion` : le lecteur devient un PAS-À-PAS. Aucune image
     n'est perdue — seule l'avance automatique cesse.
     ======================================================================= */

  var replayTimer = null;

  function replayStop() {
    if (replayTimer) { clearTimeout(replayTimer); replayTimer = null; }
  }

  function motionReduced() {
    try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    catch (e) { return false; }
  }

  var DAY_TONE = {
    jour_actif: 'ok',
    jour_machine_seule: 'warn',
    jour_sans_machine: 'warn',
    jour_vide: 'unavailable'
  };

  function replayDayPicker(dd, current) {
    var strip = el('div', { class: 'rp-days', role: 'group', 'aria-label': 'Journées rejouables' });
    (dd.days || []).forEach(function (j) {
      var c = composeSentence({ template_key: j.template_key, args: j.args }, dd.templates, dd.unknown_template);
      var b = el('button', {
        class: 'rp-day', type: 'button',
        'data-tone': DAY_TONE[j.template_key] || 'unavailable',
        'data-empty': j.is_empty ? '1' : '0',
        'aria-pressed': String(j.day) === String(current) ? 'true' : 'false',
        title: c.text
      }, [
        el('span', { class: 'rp-day-date mono', text: j.day }),
        el('span', { class: 'rp-day-n mono', text: fmtNum(j.atoms) }),
        el('span', { class: 'rp-day-mark', text: j.is_empty ? 'vide' : (j.template_key === 'jour_machine_seule' ? 'machine seule' : '') })
      ]);
      b.addEventListener('click', function () { navPatch({ day: j.day }); });
      strip.appendChild(b);
    });
    return strip;
  }

  function replayEventNode(ev, templates, unknownTpl) {
    var c = composeSentence(ev, templates, unknownTpl);
    var subj = ev.subject || {};
    var hash = targetHash(subj);
    var bits = [el('span', { class: 'rp-ev-text', text: c.text })];
    var srcs = (ev.sources || []).map(sourceChip);
    if (hash) bits.push(el('button', { class: 'pill', type: 'button', 'data-go': hash, text: '→ ' + cut(subj.label || subj.kind, 34) }));
    return el('div', {
      class: 'rp-ev', 'data-type': ev.type || 'autre', 'data-unknown': c.unknown ? '1' : '0',
      title: 'gabarit servi : ' + (ev.template_key || '?')
    }, [
      el('div', { class: 'rp-ev-line' }, bits),
      srcs.length ? el('div', { class: 'rp-ev-src' }, srcs) : null
    ]);
  }

  function viewRejeu(host, q) {
    replayStop();
    var box = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'chargement du rejeu…' }));
    host.appendChild(box);

    Promise.all([
      get(API + '/replay/days' + qs({ limit: q.days || '' })),
      get(API + '/replay' + qs({ day: q.day || '', speed: q.speed || '' }))
    ]).then(function (rs) {
      var rDays = rs[0], rPlay = rs[1];
      clear(box);
      /* Écran quitté pendant la lecture : on ne remonte pas un film sur une
         vue détachée, et surtout on n'y arme aucun minuteur. */
      if (!box.isConnected) { replayStop(); return; }

      /* --- 1 · LE SÉLECTEUR DE JOURNÉE ---------------------------------- */
      if (!rDays.ok) {
        box.appendChild(naBlock({ title: 'La liste des journées n\'a pas pu être lue', reason: rDays.reason,
          substitute: 'le rejeu du jour courant reste demandé ci-dessous' }));
      } else {
        var dd = rDays.data || {};
        if (dd.state === 'unavailable') {
          box.appendChild(naBlock({ title: 'Journées indisponibles', reason: dd.reason }));
        } else {
          var right = el('span', { class: 'tiny faint' }, [
            el('span', { text: fmtNum(dd.count) + ' journée(s) · ' + fmtNum((dd.empty_days || {}).count) + ' vide(s) · '
              + fmtNum((dd.machine_only_days || {}).count) + ' où la machine a tourné pour rien' })
          ]);
          /* La PROFONDEUR du sélecteur est un réglage d'interface, pas une
             donnée du cerveau : combien de journées on demande à voir. Le
             serveur la borne et le dit dans ses `notices` — affichées telles
             quelles, jamais devinées ici. */
          var deep = el('input', {
            type: 'number', min: '1', value: String(dd.limit),
            'aria-label': 'nombre de journées listées', class: 'rp-depth'
          });
          deep.addEventListener('change', function () { navPatch({ days: deep.value }); });
          var tools = el('div', { class: 'toolbar' }, [
            el('span', { class: 'eyebrow', text: 'journées listées' }), deep,
            registerSqlEvidence('replay-days', dd.evidence ? { label: dd.evidence.label, sql: dd.evidence.sql } : null)
          ]);
          box.appendChild(section('Quelle journée rejouer', right, el('div', { class: 'stack' }, [
            tools,
            replayDayPicker(dd, (rPlay.ok && rPlay.data && rPlay.data.range) ? rPlay.data.range.day : (q.day || '')),
            el('p', { class: 'tiny faint', text: (dd.empty_days || {}).note || '' }),
            el('div', { class: 'stack' }, (dd.notices || []).map(function (n) {
              return el('p', { class: 'tiny faint', text: n });
            }))
          ])));
        }
      }

      /* --- 2 · LE FILM --------------------------------------------------- */
      if (!rPlay.ok) {
        box.appendChild(naBlock({ title: 'Le rejeu n\'a pas pu être lu', reason: rPlay.reason,
          gesture: 'vérifier la session du Control Center et l\'accès PostgreSQL en lecture seule',
          substitute: 'la chronologie (touche 2) dit la même journée, sans la rejouer' }));
        return;
      }
      var d = rPlay.data || {};
      if (d.state === 'unavailable') {
        box.appendChild(naBlock({ title: 'Rejeu indisponible', reason: d.reason, gesture: d.gesture, substitute: d.substitute }));
        return;
      }

      var range = d.range || {};
      var templates = d.templates || null;
      var unknownTpl = d.unknown_template || null;
      var frames = d.frames || [];
      var order = d.counter_order || [];
      var labels = d.counter_labels || {};
      var reduced = motionReduced();

      var head = el('div', { class: 'toolbar' }, [
        el('span', { class: 'eyebrow', text: range.day_label || 'plage libre' }),
        el('span', { class: 'tiny faint mono', text: (range.timezone || '') + ' · ' + ((d.step || {}).label || '') }),
        el('span', { class: 'tiny faint mono', text: 'cadence servie : ' + fmtNum(d.frame_ms) + ' ms / image' }),
        registerSqlEvidence('replay', d.evidence ? { label: d.evidence.label, sql: d.evidence.sql, queries: d.evidence.queries } : null)
      ]);
      box.appendChild(head);

      /* --- LA JOURNÉE VIDE : elle le DIT, elle ne reste pas blanche ------ */
      if (d.empty && d.empty.is_empty) {
        var ec = composeSentence({ template_key: d.empty.template_key, args: d.empty.args }, templates, unknownTpl);
        box.appendChild(section('Rien à rejouer',
          el('span', { class: 'tiny faint', text: 'un jour sans apprentissage est une information' }),
          el('div', { class: 'stack' }, [
            el('p', { class: 'lede', text: ec.text }),
            naBlock({ title: 'Aucune image', reason: d.empty.reason, gesture: d.empty.gesture,
              substitute: 'les journées voisines restent rejouables dans le sélecteur ci-dessus' })
          ])));
        box.appendChild(replayNotes(d));
        return;
      }

      if (!frames.length) {
        box.appendChild(emptyBlock('Aucune image servie', 'le moteur n\'a renvoyé aucune image pour cette plage.'));
        box.appendChild(replayNotes(d));
        return;
      }

      /* --- LE TRANSPORT -------------------------------------------------- */
      var cursor = 0;
      var playing = false;

      var btnFirst = el('button', { class: 'pill', type: 'button', text: '⏮ début', 'aria-label': 'revenir à la première image' });
      var btnPrev = el('button', { class: 'pill', type: 'button', text: '‹ précédente' });
      var btnPlay = el('button', { class: 'pill rp-play', type: 'button', text: '⏵ lecture', 'aria-pressed': 'false' });
      var btnNext = el('button', { class: 'pill', type: 'button', text: 'suivante ›' });

      var speeds = el('span', { class: 'rp-speeds', role: 'group', 'aria-label': 'Vitesse de projection' });
      ((d.speed || {}).available || []).forEach(function (sp) {
        var b = el('button', {
          class: 'pill', type: 'button', text: '×' + fmtNum(sp),
          'aria-pressed': String(sp) === String((d.speed || {}).applied) ? 'true' : 'false',
          title: 'la vitesse est appliquée par le serveur : elle change frame_ms, pas la donnée'
        });
        b.addEventListener('click', function () { navPatch({ speed: sp }); });
        speeds.appendChild(b);
      });

      var transport = el('div', { class: 'rp-transport' }, [
        btnFirst, btnPrev, btnPlay, btnNext,
        el('span', { class: 'rp-sep', 'aria-hidden': 'true' }),
        speeds
      ]);

      /* --- LA FRISE ------------------------------------------------------
         Une graduation par IMAGE, dans l'ordre servi. Les images sont espacées
         d'un `frame_ms` constant : la frise est donc exactement l'axe du film.
         Aucune position n'est calculée — les graduations se partagent la
         largeur en CSS (flex), et leur heure vient de `at_label`. */
      var frise = el('div', { class: 'rp-frise', role: 'group', 'aria-label': 'Frise de la journée — sauter dans le film' });
      var ticks = [];
      frames.forEach(function (f, i) {
        var t = el('button', {
          class: 'rp-tick', type: 'button',
          'data-kind': f.events_total > 0 ? 'narratif' : 'pouls',
          'data-current': '0',
          'aria-label': 'image ' + fmtNum(f.seq) + ' — ' + f.at_label,
          title: f.at_label + ' · ' + fmtNum(f.events_total) + ' événement(s) narré(s)'
        });
        t.addEventListener('click', function () { pause(); goTo(i); });
        ticks.push(t);
        frise.appendChild(t);
      });

      /* --- L'IMAGE COURANTE ---------------------------------------------- */
      var stage = el('div', { class: 'rp-frame' });
      var counters = el('div', { class: 'rp-counters' });
      var evHost = el('div', { class: 'rp-events' });

      function paint(i) {
        var f = frames[i];
        clear(stage); clear(counters); clear(evHost);

        stage.appendChild(el('div', { class: 'rp-frame-head' }, [
          el('span', { class: 'rp-clock mono', text: f.at_label }),
          el('span', { class: 'rp-seq mono', text: 'image ' + fmtNum(f.seq) + ' / ' + fmtNum((d.truncated || {}).total) }),
          el('span', { class: 'tiny faint mono', text: fmtStamp(f.at) }),
          el('span', { class: 'tiny faint mono', text: '+' + fmtDuration(f.offset_ms) + ' de film' })
        ]));

        var cum = f.cumulative || {};
        var del = f.deltas || {};
        order.forEach(function (k) {
          var dv = del[k];
          counters.appendChild(el('div', { class: 'rp-counter', 'data-moved': (typeof dv === 'number' && dv > 0) ? '1' : '0' }, [
            el('span', { class: 'rp-counter-k', text: labels[k] || k }),
            el('span', { class: 'rp-counter-v mono', text: fmtNum(cum[k]) }),
            el('span', { class: 'rp-counter-d mono', text: (typeof dv === 'number' && dv > 0) ? '+' + fmtNum(dv) : '' })
          ]));
        });

        var evs = f.events || [];
        if (!evs.length) {
          evHost.appendChild(el('p', { class: 'tiny faint', text: 'cette image ne porte aucun événement narré : ce qui a bougé est dit par ses compteurs.' }));
        } else {
          evs.forEach(function (ev) { evHost.appendChild(replayEventNode(ev, templates, unknownTpl)); });
        }
        if (f.events_truncated) {
          evHost.appendChild(el('p', { class: 'tiny faint', text: 'image tronquée : ' + fmtNum(f.events_total)
            + ' événement(s) à cet instant, ' + fmtNum((d.truncated || {}).events_per_frame) + ' détaillés au plus.' }));
        }

        for (var t = 0; t < ticks.length; t++) ticks[t].setAttribute('data-current', t === i ? '1' : '0');
      }

      function goTo(i) {
        if (i < 0) i = 0;
        if (i > frames.length - 1) i = frames.length - 1;
        cursor = i;
        paint(cursor);
      }

      /* Le libellé du bouton dit TOUJOURS ce que le bouton fait. Quand le
         mouvement est refusé, il ne redevient jamais « lecture » : un bouton
         inerte qui promet la lecture est un mensonge d'interface. */
      function pause() {
        playing = false;
        replayStop();
        btnPlay.textContent = reduced ? '⏵ lecture coupée' : '⏵ lecture';
        btnPlay.setAttribute('aria-pressed', 'false');
      }

      /* L'avance est déclenchée sur la CADENCE SERVIE. Aucune durée n'est
         calculée ici : `frame_ms` est le pas du film, et `offset_ms` (servi
         par chaque image) en est la confirmation, image après image. */
      function tick() {
        replayTimer = setTimeout(function () {
          replayTimer = null;
          if (!playing) return;
          if (cursor >= frames.length - 1) { pause(); return; }
          goTo(cursor + 1);
          tick();
        }, d.frame_ms);
      }

      function play() {
        if (reduced) return;
        if (cursor >= frames.length - 1) goTo(0);
        playing = true;
        btnPlay.textContent = '⏸ pause';
        btnPlay.setAttribute('aria-pressed', 'true');
        tick();
      }

      btnPlay.addEventListener('click', function () { if (playing) pause(); else play(); });
      btnNext.addEventListener('click', function () { pause(); goTo(cursor + 1); });
      btnPrev.addEventListener('click', function () { pause(); goTo(cursor - 1); });
      btnFirst.addEventListener('click', function () { pause(); goTo(0); });

      if (reduced) {
        btnPlay.disabled = true;
        btnPlay.textContent = '⏵ lecture coupée';
        btnPlay.title = 'le mouvement est refusé par vos préférences système';
      }

      box.appendChild(section('Le lecteur',
        el('span', { class: 'tiny faint', text: (d.step || {}).elected_by || '' }),
        el('div', { class: 'stack' }, [
          transport,
          reduced ? el('p', { class: 'tiny faint', text: 'Mouvement refusé par vos préférences système : le lecteur est en PAS-À-PAS. Toutes les images restent atteignables — image par image ou par la frise. Aucune information n\'est perdue.' }) : null,
          frise,
          el('p', { class: 'tiny faint', text: 'une graduation par image, dans l\'ordre servi ; les images pleines portent un événement narré, les creuses ne portent qu\'un pouls de volume.' }),
          stage,
          section('Ce que l\'image compte', el('span', { class: 'tiny faint', text: d.cumulative_note || '' }), counters),
          section('Ce que l\'image raconte', el('span', { class: 'tiny faint', text: d.events_note || '' }), evHost)
        ])));

      /* --- LES TOTAUX, PAR UN AUTRE CHEMIN ------------------------------- */
      var tot = d.totals || {};
      box.appendChild(section('Les totaux de la plage',
        el('span', { class: 'tiny faint', text: 'calculés par une requête séparée : le dernier cumul doit les égaler' }),
        el('div', { class: 'rp-counters' }, order.map(function (k) {
          return el('div', { class: 'rp-counter', 'data-moved': '0' }, [
            el('span', { class: 'rp-counter-k', text: labels[k] || k }),
            el('span', { class: 'rp-counter-v mono', text: fmtNum(tot[k]) }),
            el('span', { class: 'rp-counter-d mono', text: '' })
          ]);
        }))));

      box.appendChild(replayNotes(d));
      goTo(0);
    });
  }

  /* Ce que le rejeu NE MONTRE PAS, et pourquoi. Servi par le moteur
     (`blind_spots`) : un film doit pouvoir dire ce qu'il ne filme pas. */
  function replayNotes(d) {
    var wrap = el('div', { class: 'stack' });
    var spots = d.blind_spots || [];
    if (spots.length) {
      wrap.appendChild(section('Ce que le rejeu ne sait pas montrer',
        el('span', { class: 'tiny faint', text: 'une mesure absente n\'est jamais un zéro' }),
        el('div', { class: 'stack' }, spots.map(function (b) {
          return naBlock({ title: b.measure, reason: b.reason, gesture: b.gesture, substitute: b.substitute });
        }))));
    }
    var tr = d.truncated || {};
    var lines = [];
    if (tr.applied) lines.push('rejeu tronqué : ' + fmtNum(tr.shown) + ' images servies sur ' + fmtNum(tr.total) + '.');
    if (d.rejected_events) lines.push(fmtNum(d.rejected_events) + ' événement(s) écarté(s) faute de source résolvable.');
    (d.notices || []).forEach(function (n) { lines.push(n); });
    if (lines.length) {
      wrap.appendChild(el('div', { class: 'stack' }, lines.map(function (t) {
        return el('p', { class: 'tiny faint', text: t });
      })));
    }
    return wrap;
  }

  /* =======================================================================
     15 · NAVIGATION
     ======================================================================= */

  /* Deux groupes, deux intentions. En haut, LA VIE du cerveau : ce qu'il
     apprend, retient, oublie, ne comprend pas. En bas, les MESURES du socle
     V1, inchangées. Aucun écran n'a été retiré. */
  var NAV = [
    { id: 'aujourdhui', key: '1', label: 'Aujourd\'hui', group: 'la vie du cerveau', domain: 'aujourdhui' },
    { id: 'chronologie', key: '2', label: 'Chronologie', group: 'la vie du cerveau' },
    { id: 'cascade', key: 'k', label: 'Le cerveau pense', group: 'la vie du cerveau' },
    { id: 'rejeu', key: 'j', label: 'Rejeu', group: 'la vie du cerveau' },
    { id: 'atomes', key: '3', label: 'Atomes', group: 'la vie du cerveau', domain: 'atomes' },
    { id: 'scopes', key: '4', label: 'Scopes', group: 'la vie du cerveau' },
    { id: 'projets', key: '5', label: 'Projets', group: 'la vie du cerveau', domain: 'projets' },
    { id: 'confiance', key: '6', label: 'Confiance', group: 'la vie du cerveau', domain: 'confiance' },
    { id: 'conversations', key: '7', label: 'Conversations', group: 'la vie du cerveau', domain: 'conversations' },
    { id: 'general', key: '8', label: 'État général', group: 'les mesures' },
    { id: 'activite', key: '9', label: 'Activité', group: 'les mesures' },
    { id: 'digestion', key: '0', label: 'Digestion', group: 'les mesures', domain: 'digestion' },
    { id: 'rappel', key: '-', label: 'Rappel', group: 'les mesures', domain: 'rappel' },
    { id: 'memoire', key: '=', label: 'Mémoire', group: 'les mesures', domain: 'memoire' },
    { id: 'croissance', key: 'c', label: 'Croissance', group: 'les mesures', domain: 'croissance' },
    { id: 'pipeline', key: 'p', label: 'Pipeline', group: 'les mesures', domain: 'pipeline' },
    { id: 'graphes', key: 'g', label: 'Graphes', group: 'les mesures', domain: 'graphes' },
    { id: 'audits', key: 'a', label: 'Audits', group: 'les mesures', domain: 'audits' },
    { id: 'observabilite', key: 'o', label: 'Observabilité', group: 'les mesures', domain: 'observabilite' }
  ];

  var TITLES = {
    aujourdhui: ['Aujourd\'hui', 'Ce que le cerveau a appris, retenu, remplacé, raté et coûté — et ce qu\'il ne sait pas mesurer.'],
    chronologie: ['Chronologie', 'Rejouer une journée du cerveau : la bande du temps, puis les faits, dans l\'ordre.'],
    cascade: ['Le cerveau pense', 'Le trajet d\'une conversation dans un cycle, étape par étape : détectée, absorbée, analysée, retenue — ou perdue. Chaque étape porte sa phrase, sa cible et sa preuve.'],
    rejeu: ['Rejeu', 'Rejouer une journée image par image. La cadence, les cumuls et les phrases viennent du moteur : ce lecteur ne fait que projeter.'],
    scopes: ['Scopes', 'Les territoires du savoir. Un atome posé sur une RACINE existe en base et ne remonte jamais au rappel.'],
    confiance: ['Confiance', 'Où le cerveau doute — et où il ne sait même pas qu\'il devrait douter.'],
    general: ['État général', 'Ce que le cerveau vaut à cet instant, et ce qui le retient.'],
    croissance: ['Croissance', 'Ce que le savoir gagne et perd dans la durée.'],
    activite: ['Activité', 'Le cerveau travaille quelques fois par jour. Le reste du temps, il attend — et cette attente est une information.'],
    conversations: ['Conversations', 'Ce qui entre. Chaque conversation porte sa chaîne, son statut dérivé et son rang de file.'],
    atomes: ['Atomes', 'Le savoir lui-même : ce que le cerveau a retenu, et ce qu\'on lui a jamais redemandé.'],
    graphes: ['Graphes', 'Le maillon qui relie les atomes entre eux. Non branché — et affiché comme tel.'],
    digestion: ['Digestion', 'Ce qui se perd entre deux maillons, et pourquoi.'],
    memoire: ['Mémoire', 'La forme du savoir : ses territoires, son âge, sa part dormante.'],
    rappel: ['Rappel', 'Ce que le cerveau retrouve quand on le lui demande — et à quelle confiance.'],
    audits: ['Audits', 'Ce que les outils ont fait, et ce qui a échoué.'],
    pipeline: ['Pipeline', 'De la capture au rappel : le débit et le coût de chaque étage.'],
    projets: ['Projets', 'Un projet est une règle de sélection, pas un dossier.'],
    observabilite: ['Observabilité', 'Le cockpit vu par lui-même : ce qui est chargé, ce qui manque, ce qui ne s\'accorde pas.']
  };

  function parseHash() {
    var raw = window.location.hash.replace(/^#/, '');
    if (!raw) raw = '/aujourdhui';
    var qi = raw.indexOf('?');
    var path = qi >= 0 ? raw.slice(0, qi) : raw;
    var query = {};
    if (qi >= 0) {
      var sp = new URLSearchParams(raw.slice(qi + 1));
      sp.forEach(function (v, k) { query[k] = v; });
    }
    var parts = path.split('/').filter(function (p) { return p !== ''; });
    return { seg: parts, query: query };
  }

  function go(hash) { window.location.hash = hash; }

  function navPatch(patch) {
    var r = parseHash();
    var q = r.query;
    for (var k in patch) {
      if (!Object.prototype.hasOwnProperty.call(patch, k)) continue;
      var v = patch[k];
      if (v === '' || v === null || v === undefined) delete q[k]; else q[k] = v;
    }
    go('#/' + r.seg.join('/') + qs(q));
  }

  function renderNav(active) {
    var rail = $('#rail');
    clear(rail);
    var groups = {}, order = [];
    NAV.forEach(function (n) {
      var g = n.group || 'domaines';
      if (!hasOwn(groups, g)) { groups[g] = []; order.push(g); }
      groups[g].push(n);
    });
    order.forEach(function (gname) {
      var group = el('div', { class: 'rail-group' }, el('div', { class: 'rail-title eyebrow', text: gname }));
      groups[gname].forEach(function (n) {
        /* Le compte affiché est un INVENTAIRE D'INTERFACE : combien de mesures
           cet écran servira. Ce n'est pas une donnée du cerveau, et la liste
           n'est jamais tronquée — le registre est servi en entier. */
        var howMany = n.domain ? metricsOf(n.domain).length : null;
        var b = el('button', {
          class: 'nav-item', type: 'button', 'data-go': '#/' + n.id,
          'data-empty': (n.domain && !howMany) ? '1' : '0',
          'aria-current': active === n.id ? 'page' : 'false'
        }, [
          el('span', { class: 'nav-key', text: n.key }),
          el('span', { text: n.label }),
          el('span', { class: 'nav-count', text: howMany === null ? '' : String(howMany) })
        ]);
        group.appendChild(b);
      });
      rail.appendChild(group);
    });
    rail.appendChild(el('div', { class: 'rail-group', style: 'margin-top:auto' }, [
      el('div', { class: 'rail-title eyebrow', text: 'clavier' }),
      el('button', { class: 'nav-item', type: 'button', 'data-help': '1' }, [
        el('span', { class: 'nav-key', text: '?' }),
        el('span', { text: 'raccourcis' }), el('span', {})
      ])
    ]));
  }

  function render() {
    var r = parseHash();
    S.route = r;
    var head = r.seg[0] || 'aujourdhui';
    var sub = r.seg[1] ? decodeURIComponent(r.seg[1]) : null;
    /* Un scope s'écrit « racine/feuille » : son chemin occupe PLUSIEURS
       segments. Les recoller ici fait marcher les deux formes servies —
       « #/scopes/travail/finance » comme « #/scopes/travail%2Ffinance ». */
    var deep = r.seg.slice(1).map(function (s) {
      try { return decodeURIComponent(s); } catch (e) { return s; }
    }).join('/');
    closeDrawer();
    /* Deux dettes de l'écran précédent, soldées avant d'en ouvrir un autre :
       le film qui tournait encore, et le crochet posé sur le flux. */
    replayStop();
    S.liveHook = null;
    renderNav(head);

    var view = $('#view');
    clear(view);
    view.scrollTop = 0;

    var t = TITLES[head];
    if (t && !sub) {
      view.appendChild(el('div', { class: 'view-head' }, [
        el('h1', { class: 'view-title', text: t[0] }),
        el('p', { class: 'view-sub', text: t[1] })
      ]));
    }

    if (S.metricsError) {
      view.appendChild(naBlock({
        title: 'Les mesures ne sont pas lisibles',
        reason: S.metricsError,
        gesture: 'vérifier la session du Control Center et l\'accès PostgreSQL en lecture seule',
        substitute: 'les écrans de navigation restent servis par leurs propres routes'
      }));
    }

    switch (head) {
      case 'aujourdhui': viewAujourdhui(view, r.query); break;
      case 'chronologie': viewChronologie(view, r.query); break;
      case 'cascade': viewCascade(view, deep || sub); break;
      case 'rejeu': viewRejeu(view, r.query); break;
      case 'confiance': viewConfiance(view); break;
      case 'general': viewGeneral(view); break;
      case 'activite': viewActivite(view); break;
      case 'conversations': sub ? viewConversation(view, sub) : viewConversations(view, r.query); break;
      /* `?vue=fiche` ouvre la fiche d'état (/cc/v1/atoms/{id}), sans paramètre on
         garde l'histoire — le comportement en place. Voir `atomeVueToggle`. */
      case 'atomes':
        if (!sub) viewAtomes(view, r.query);
        else if (r.query.vue === 'fiche') viewAtome(view, sub);
        else viewAtomeStory(view, sub);
        break;
      case 'scopes': deep ? viewScopeDetail(view, deep) : viewScopesTree(view); break;
      case 'graphes': viewGraphes(view); break;
      case 'memoire': viewMemoire(view); break;
      case 'projets': sub ? viewProjet(view, sub) : viewProjets(view); break;
      case 'observabilite': viewObservabilite(view); break;
      case 'digestion': viewDigestion(view); break;
      default:
        if (TITLES[head]) viewDomain(view, head);
        else view.appendChild(emptyBlock('Écran inconnu', 'la route « ' + head + ' » n\'existe pas dans ce cockpit.'));
    }
  }

  function viewDigestion(host) {
    viewDomain(host, 'digestion');
    var chainHost = el('div', { class: 'stack' }, el('div', { class: 'spin', text: 'lecture de l\'entonnoir…' }));
    host.appendChild(section('L\'entonnoir, maillon par maillon', null, chainHost));
    get(API + '/evidence/' + HEALTH_SUBSTITUTE + '?limit=10').then(function (r) {
      clear(chainHost);
      if (!r.ok || !r.data || r.data.state === 'unavailable') {
        chainHost.appendChild(naBlock({ title: 'Entonnoir illisible', reason: (r.data && r.data.reason) || r.reason }));
        return;
      }
      chainHost.appendChild(chainNode(chainFromFunnel(r.data), function () { openMetricEvidence(HEALTH_SUBSTITUTE); }));
      chainHost.appendChild(el('div', { class: 'hr' }));
      chainHost.appendChild(chainLegend());
    });
  }

  /* =======================================================================
     16 · CLAVIER
     ======================================================================= */

  function bindKeys() {
    document.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      var typing = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';

      if (e.key === 'Escape') {
        if ($('#help').getAttribute('data-open') === '1') { $('#help').setAttribute('data-open', '0'); return; }
        if (drawer.getAttribute('data-open') === '1') { closeDrawer(); return; }
        if (typing) e.target.blur();
        return;
      }
      if (typing) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === '?') { e.preventDefault(); toggleHelp(); return; }
      if (e.key === '/') { e.preventDefault(); var f = $('#view').querySelector('input[type=search]'); if (f) f.focus(); return; }
      if (e.key === 'f') { e.preventDefault(); toggleFlux(); return; }
      if (e.key === 'r') { e.preventDefault(); reloadAll(); return; }

      for (var i = 0; i < NAV.length; i++) {
        if (e.key === NAV[i].key) { e.preventDefault(); go('#/' + NAV[i].id); return; }
      }
    });
  }

  function toggleHelp() {
    var h = $('#help');
    h.setAttribute('data-open', h.getAttribute('data-open') === '1' ? '0' : '1');
  }

  function toggleFlux() {
    var f = $('#flux');
    var open = f.getAttribute('data-open') === '1' ? '0' : '1';
    f.setAttribute('data-open', open);
    $('#flux-toggle').setAttribute('aria-expanded', open === '1' ? 'true' : 'false');
    try { window.localStorage.setItem('arac.flux', open); } catch (err) {}
  }

  function renderHelp() {
    var rows = [];
    NAV.forEach(function (n) { rows.push([n.key, n.label]); });
    rows.push(['/', 'chercher dans l\'écran courant']);
    rows.push(['f', 'replier / déplier le flux d\'activité']);
    rows.push(['r', 'relire toutes les mesures']);
    rows.push(['Échap', 'fermer le tiroir de preuve']);
    rows.push(['?', 'cette aide']);
    var card = $('#help-card');
    clear(card);
    card.appendChild(el('h2', { class: 'view-title', text: 'Clavier' }));
    card.appendChild(el('p', { class: 'small muted', text: 'Le cockpit se conduit sans souris. Le focus clavier est toujours visible, en lilas.' }));
    rows.forEach(function (r) {
      card.appendChild(el('div', { class: 'help-row' }, [el('div', {}, el('kbd', { text: r[0] })), el('div', { text: r[1] })]));
    });
    var close = el('button', { class: 'pill', type: 'button', text: 'fermer' });
    close.addEventListener('click', toggleHelp);
    card.appendChild(el('div', { class: 'toolbar', style: 'margin-top:16px' }, close));
  }

  /* =======================================================================
     17 · DÉMARRAGE
     ======================================================================= */

  function reloadAll() {
    return Promise.all([
      loadMetrics(),
      get(API + '/status').then(function (r) { if (r.ok) S.status = r.data; }),
      refreshStreamState()
    ]).then(function () { renderVitals(); render(); });
  }

  function bindGlobalClicks() {
    document.addEventListener('click', function (e) {
      var t = e.target;
      var b = t && t.closest ? t.closest('[data-metric],[data-sql],[data-go],[data-view],[data-help]') : null;
      if (!b) return;
      if (b.hasAttribute('data-metric')) {
        e.preventDefault();
        /* `data-window` n'est posé que par les cartes de fenêtre (« Aujourd'hui »).
           Absent, la preuve reste celle du registre — inchangée. */
        openMetricEvidence(b.getAttribute('data-metric'), b.getAttribute('data-window') || null);
        return;
      }
      if (b.hasAttribute('data-sql')) { e.preventDefault(); openSqlEvidence(b.getAttribute('data-sql')); return; }
      if (b.hasAttribute('data-go')) { e.preventDefault(); go(b.getAttribute('data-go')); return; }
      if (b.hasAttribute('data-view')) { e.preventDefault(); go('#/' + b.getAttribute('data-view')); return; }
      if (b.hasAttribute('data-help')) { e.preventDefault(); toggleHelp(); return; }
    });
  }

  function boot() {
    drawer = $('#drawer'); scrim = $('#scrim');
    drawerTitle = $('#drawer-title'); drawerEyebrow = $('#drawer-eyebrow'); drawerBody = $('#drawer-body');

    $('.drawer-close').addEventListener('click', closeDrawer);
    scrim.addEventListener('click', closeDrawer);
    $('#flux-toggle').addEventListener('click', toggleFlux);
    $('#help').addEventListener('click', function (e) { if (e.target === $('#help')) toggleHelp(); });

    try {
      var pref = window.localStorage.getItem('arac.flux');
      if (pref === '0' || pref === '1') {
        $('#flux').setAttribute('data-open', pref);
        $('#flux-toggle').setAttribute('aria-expanded', pref === '1' ? 'true' : 'false');
      }
    } catch (err) {}

    bindGlobalClicks();
    bindKeys();
    renderHelp();
    setMode('init', 'connexion au flux');

    window.addEventListener('hashchange', render);

    /* Le catalogue d'abord : sans lui, aucune phrase d'événement ne peut être
       composée — et on préfère ne rien écrire plutôt qu'écrire au hasard. */
    get(API + '/stream/catalog').then(function (r) {
      if (r.ok && r.data) {
        S.msgCatalog = r.data.message_catalog || {};
        S.transport = r.data.transport || null;
      } else {
        setMode('down', r.reason || 'catalogue du flux indisponible');
      }
      return reloadAll();
    }).then(function () {
      if (S.msgCatalog) connectSSE();
      /* le repos se relit doucement : un compte à rebours doit rester juste */
      setInterval(refreshStreamState, 60000);
      setInterval(function () {
    /* Ne jamais arracher le focus : `renderVitals()` détruit les cinq
       tuiles du bandeau. Si le clavier en tient une, on saute ce tour —
       une interface qui se pilote au clavier ne peut pas se redessiner
       sous les doigts toutes les 30 secondes. La garde vit désormais dans
       `renderVitalsSafely()`, partagée par tous les chemins automatiques. */
    renderVitalsSafely(); renderRest();
  }, 30000);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
