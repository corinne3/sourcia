// Parcours enseignant, étapes 3 (Mon corpus) et 4 (Mes supports), dans la page des dossiers.
// Même page que « Mon dossier » : le jeton reste en mémoire, comme le veut dossiers.html (jamais enregistré).
// Ce script réutilise ce que dossiers.html déclare : token, folder, base, byId, json, request, message.
// Tout le texte venu de l'API est inséré avec textContent (jamais innerHTML) : pas d'injection de HTML.
'use strict';
(() => {
  const STEPS = ['dossier', 'corpus', 'supports'];
  const POLL_MS = 3000;
  const STATUT = {en_cours: 'en cours', pret: 'prêt', erreur: 'erreur'};
  const CAPACITE = {propose_ia: "proposé par l'IA, à valider", repli: 'proposé (plan sans modèle), à valider',
    ajoute_couverture: 'ajouté pour couvrir la capacité, à valider', deja_valide: 'déjà validé',
    valide: 'validé', refuse: 'refusé'};
  const FICHIERS = {
    'qcm_apprenants.md': 'QCM pour les élèves', 'qcm_corrige.md': 'QCM corrigé', 'qcm_moodle.gift.txt': 'QCM Moodle (GIFT)',
    'cartes_anki.csv': 'Cartes pour Anki (CSV)', 'cartes.html': 'Cartes à découper', 'infographie.html': 'Infographie A4',
    'presentation.pptx': 'Présentation', 'fiche_technique.md': 'Fiche technique', 'glossaire.md': 'Glossaire',
    'podcast_script.md': 'Script de podcast', 'supports.json': 'Données (JSON)'};
  const NOMS = {qcm: 'QCM', cartes: 'cartes', presentation: 'présentation', infographie: 'infographie',
    fiche: 'fiche technique', glossaire: 'glossaire', podcast: 'podcast'};
  const state = {step: 'dossier', corpus: '', timer: null, images: [], refs: null, loading: 0};

  // ------------------------------------------------------------------ petits outils
  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'text') node.textContent = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key in node) node[key] = value;
      else node.setAttribute(key, value);
    }
    node.append(...children.filter(child => child !== null && child !== undefined && child !== false));
    return node;
  }
  const folderUrl = () => base + '/' + encodeURIComponent(folder);
  const corpusUrl = cid => folderUrl() + '/corpus-pedagogique' + (cid ? '/' + encodeURIComponent(cid) : '');
  const dateFr = iso => iso ? new Date(iso).toLocaleString('fr-FR', {dateStyle: 'short', timeStyle: 'short'}) : '';
  const isWeb = url => typeof url === 'string' && /^https?:\/\//i.test(url);

  function status(id, text, error = false) {
    byId(id).textContent = text;
    byId(id).dataset.error = error;
  }

  function badge(statut) {
    return el('span', {className: 'document-status', dataset: {status: statut || ''}, text: STATUT[statut] || statut || '?'});
  }

  function action(text, run, secondary = true) {
    const b = el('button', {type: 'button', className: secondary ? 'secondary' : '', text});
    b.addEventListener('click', async () => {
      b.disabled = true;
      try { await run(); } catch (error) { message(error.message, true); } finally { b.disabled = false; }
    });
    return b;
  }

  // fichiers protégés par jeton : le navigateur les récupère avec le jeton (comme le ZIP de dossiers.html)
  async function download(path, filename) {
    const response = await request(path);
    const url = URL.createObjectURL(await response.blob());
    el('a', {href: url, download: filename}).click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async function openInTab(path) {
    const response = await request(path);
    const blob = new Blob([await response.blob()], {type: 'text/html'});
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  function stopPolling() {
    clearTimeout(state.timer);
    state.timer = null;
  }

  function freeImages() {
    for (const url of state.images) URL.revokeObjectURL(url);
    state.images = [];
  }

  // ------------------------------------------------------------------ navigation entre les étapes
  function stepFromHash() {
    const step = location.hash.slice(1);
    return STEPS.includes(step) ? step : 'dossier';
  }

  function show(step) {
    state.step = step;
    stopPolling();
    document.body.dataset.step = step;
    document.querySelectorAll('nav.steps a[data-step]').forEach(a => {
      if (a.dataset.step === step) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const logged = Boolean(token);
    byId('step-hint').hidden = !logged || step === 'dossier' || Boolean(folder);
    byId('step-corpus').hidden = !logged || step !== 'corpus' || !folder;
    byId('step-supports').hidden = !logged || step !== 'supports' || !folder;
    if (!logged || !folder) return;
    const run = step === 'corpus' ? refreshCorpus : step === 'supports' ? refreshSupports : null;
    if (run) run().catch(error => message(error.message, true));
  }

  function goto(step) {
    if (location.hash === '#' + step) show(step);
    else location.hash = step;                     // déclenche hashchange → show()
  }

  // ------------------------------------------------------------------ écran Corpus
  async function loadReferentiels() {
    if (state.refs) return;
    const response = await fetch('/api/referentiels', {cache: 'no-store'});
    state.refs = response.ok ? await response.json() : [];
    byId('corpus-referentiel').replaceChildren(
      ...state.refs.map(r => el('option', {value: r.id, text: `${r.nom} (v${r.version})`})));
    showCaps();
  }

  function showCaps() {
    const ref = (state.refs || []).find(r => r.id === byId('corpus-referentiel').value);
    byId('corpus-caps').replaceChildren(...(ref ? ref.capacites : []).map(c => el('label',
      {className: c.parent ? 'child' : ''}, el('input', {type: 'checkbox', value: c.code}),
      el('span', {}, el('b', {text: c.code}), ' ' + c.libelle))));
  }

  async function refreshCorpus() {
    const current = folder;
    const [detail, list] = await Promise.all([json(folderUrl()), json(corpusUrl())]);
    if (current !== folder || state.step !== 'corpus') return;
    await loadReferentiels();
    const ready = detail.documents.filter(d => d.selected && d.status === 'pret');
    const waiting = detail.documents.filter(d => d.selected && d.status !== 'pret' && d.status !== 'erreur');
    const privateDocs = ready.filter(d => d.private).length;
    const box = byId('corpus-ready');
    if (ready.length) {
      box.replaceChildren(`${ready.length} document(s) coché(s) et prêt(s)` +
        (privateDocs ? `, dont ${privateDocs} PDF téléversé(s) (privé(s))` : '') +
        (waiting.length ? `. ${waiting.length} autre(s) encore en traitement, pas pris en compte` : '') + '.');
      box.dataset.error = false;
    } else {
      box.replaceChildren('Aucun document coché et prêt dans ce dossier. ',
        el('a', {href: '#dossier', text: 'Cochez des documents dans « Mon dossier »'}),
        waiting.length ? ' (certains sont encore en traitement).' : '.');
      box.dataset.error = true;
    }
    byId('corpus-go').disabled = !ready.length || list.some(c => c.statut === 'en_cours');
    renderCorpusList(list);
    if (list.some(c => c.statut === 'en_cours')) {
      state.timer = setTimeout(() => refreshCorpus().catch(error => message(error.message, true)), POLL_MS);
    }
  }

  function renderCorpusList(list) {
    const ul = byId('corpus-list');
    if (!list.length) {
      ul.replaceChildren(el('li', {className: 'empty', text: 'Aucun corpus pour ce dossier : remplissez la demande ci-dessus.'}));
      return;
    }
    ul.replaceChildren(...list.map(c => {
      const li = el('li', {dataset: {id: c.id}}, el('strong', {text: c.sujet || c.id}), ' ', badge(c.statut),
        el('div', {className: 'meta', text: `Lancé le ${dateFr(c.cree_le)} avec ${c.documents ?? '?'} document(s)` +
          (c.demande_par ? `, par ${c.demande_par}` : '') + '.'}));
      if (c.statut === 'en_cours') li.append(el('div', {className: 'meta',
        text: 'Construction en cours : avec un vrai modèle, compter plusieurs minutes. La page se met à jour seule.'}));
      if (c.statut === 'erreur') li.append(el('div', {className: 'alert', text: c.erreur || 'Échec de la construction.'}));
      if (c.exclus_prives && c.exclus_prives.length) li.append(el('div', {className: 'alert',
        text: `Documents privés laissés de côté (modèle en ligne, sans votre accord) : ${c.exclus_prives.join(', ')}.`}));
      if (c.statut === 'pret') {
        li.append(el('div', {className: 'file-actions'},
          action('Voir le corpus', () => openCorpus(c.id), false),
          action('Word', () => download(corpusUrl(c.id) + '/corpus_pedagogique.docx', 'corpus_pedagogique.docx')),
          action('JSON', () => download(corpusUrl(c.id) + '/corpus.json', 'corpus.json')),
          action('Produire les supports', async () => { state.corpus = c.id; goto('supports'); })));
      }
      if (c.id === state.corpus) li.classList.add('current');
      return li;
    }));
  }

  function refNode(ref, nums) {
    const label = `${nums[ref.doc_id] || 'Source'}, page ${ref.page}`;          // l'étiquette remplace les crochets
    return isWeb(ref.lien)
      ? el('a', {href: ref.lien, target: '_blank', rel: 'noopener', className: 'ref', title: ref.extrait || '',
        text: label})
      : el('span', {className: 'ref', title: ref.extrait || '', text: label});
  }

  function itemNode(text, ref, nums) {
    const li = el('li', {}, text + ' ', refNode(ref, nums));
    if (ref.extrait && ref.extrait !== text) {
      li.append(el('details', {}, el('summary', {text: 'Extrait du document'}), el('q', {text: ref.extrait})));
    }
    return li;
  }

  async function figureNode(ill, n, nums, cid) {
    const img = el('img', {alt: ill.legende || 'Illustration'});
    try {
      const response = await request(corpusUrl(cid) + '/' + ill.chemin.split('/').map(encodeURIComponent).join('/'));
      const url = URL.createObjectURL(await response.blob());
      state.images.push(url);
      img.src = url;
    } catch {
      img.alt = 'Illustration indisponible';
    }
    const num = nums[ill.doc_id];
    const caption = /^(fig|tableau|photo|graphique|carte|sch[ée]ma|illustration)/i.test(ill.legende || '')
      ? ill.legende : `Figure ${n}` + (ill.legende ? ` : ${ill.legende}` : '');
    return el('figure', {}, img, el('figcaption', {text: `${caption} (${num ? num + ', ' : ''}p. ${ill.page})`}));
  }

  async function openCorpus(cid) {
    const cp = await json(corpusUrl(cid) + '/corpus.json');
    state.corpus = cid;
    freeImages();
    const nums = Object.fromEntries(cp.bibliographie.filter(b => b.numero).map(b => [b.doc_id, b.numero]));
    const view = byId('corpus-view');
    const parts = [el('h2', {text: cp.titre}),
      el('p', {className: 'meta', text: `Construit le ${dateFr(cp.cree_le)} à partir de ${cp.doc_ids.length} document(s), ` +
        `en ${cp.sequences.length} séquence(s)` + (cp.referentiel ? `, pour le diplôme ${cp.referentiel.nom}` : '') + '.'})];
    if (cp.echecs_modele && cp.echecs_modele.length) parts.push(el('p', {className: 'alert',
      text: "Le modèle n'a pas répondu correctement à certaines demandes : plan de repli ou points clés incomplets. " +
        'Vérifiez que le modèle est joignable, puis relancez la construction.'}));
    if (cp.exclus_prives && cp.exclus_prives.length) parts.push(el('p', {className: 'alert',
      text: `Documents privés laissés de côté (modèle en ligne, sans votre accord) : ${cp.exclus_prives.join(', ')}. ` +
        'Cochez « Autoriser l’envoi de mes documents privés » et relancez pour les inclure.'}));
    let figure = 0;
    for (const [i, s] of cp.sequences.entries()) {
      const head = [el('h3', {text: `Séquence ${i + 1} : ${s.titre}`}),
        el('p', {}, el('b', {text: 'Objectif : '}), `${s.objectif} (${s.duree_min} min)`)];
      if (s.capacite) head.push(el('p', {}, el('b', {text: 'Capacité : '}), `${s.capacite} – ${s.capacite_libelle || ''} `,
        el('span', {className: 'tag', text: CAPACITE[s.capacite_statut] || s.capacite_statut})));
      const points = s.points.length
        ? el('ul', {className: 'points'}, ...s.points.map(p => itemNode(p.texte, p.reference, nums)))
        : el('p', {className: 'meta', text: 'Aucun point clé retenu par les contrôles : à compléter.'});
      const figures = [];
      for (const ill of cp.illustrations.filter(x => x.sequence === i + 1)) {
        figures.push(await figureNode(ill, ++figure, nums, cid));
      }
      parts.push(el('article', {className: 'sequence'}, ...head, points, ...figures,
        s.a_retenir ? el('p', {}, el('b', {text: 'À retenir : '}), s.a_retenir) : null));
    }
    if (cp.synthese && cp.synthese.paragraphes.length) {
      parts.push(el('article', {className: 'sequence'}, el('h3', {text: 'Synthèse'}),
        el('ul', {className: 'points'}, ...cp.synthese.paragraphes.map(p => itemNode(p.texte, p.reference, nums))),
        cp.synthese.conclusion ? el('p', {}, el('b', {text: 'Conclusion : '}), cp.synthese.conclusion) : null));
    }
    const loose = cp.illustrations.filter(x => !x.sequence || x.sequence > cp.sequences.length);
    if (loose.length) {
      const figures = [];
      for (const ill of loose) figures.push(await figureNode(ill, ++figure, nums, cid));
      parts.push(el('article', {className: 'sequence'}, el('h3', {text: 'Illustrations'}), ...figures));
    }
    const cited = cp.bibliographie.filter(b => b.citee);
    parts.push(el('article', {className: 'sequence'}, el('h3', {text: 'Sources'}),
      el('ol', {className: 'sources'}, ...cited.map(b => el('li', {},
        el('b', {text: b.numero + '. '}),
        [b.organisme, b.annee ? `(${b.annee})` : ''].filter(Boolean).join(' ') + (b.organisme || b.annee ? '. ' : ''),
        el('i', {text: b.titre}), '. ',
        b.fourni_par_formateur ? 'Document fourni par le formateur.' : isWeb(b.url)
          ? el('a', {href: b.url, target: '_blank', rel: 'noopener', text: 'ouvrir le document'})
          : b.url === null ? 'Document privé.' : 'Fichier local.',
        b.pages_citees.length ? ` Pages citées : ${b.pages_citees.join(', ')}.` : '')))));
    if (cp.remarques && cp.remarques.length) {
      parts.push(el('details', {}, el('summary', {text: `Remarques (${cp.remarques.length})`}),
        el('ul', {}, ...cp.remarques.map(r => el('li', {text: r})))));
    }
    parts.push(el('div', {className: 'file-actions'},
      action('Télécharger le Word', () => download(corpusUrl(cid) + '/corpus_pedagogique.docx', 'corpus_pedagogique.docx'), false),
      action('Télécharger le JSON', () => download(corpusUrl(cid) + '/corpus.json', 'corpus.json')),
      action('Produire les supports', async () => goto('supports'))));
    view.replaceChildren(...parts);
    view.hidden = false;
    view.scrollIntoView({behavior: 'smooth', block: 'start'});
    document.querySelectorAll('#corpus-list li').forEach(li => li.classList.toggle('current', li.dataset.id === cid));
  }

  function demande(form) {
    const data = new FormData(form);
    const dip = data.get('diplomante') === 'on';
    return {
      demande: {sujet: String(data.get('sujet') || '').trim(), apprenants: data.get('apprenants'),
        niveau: data.get('niveau'), experience: data.get('experience'),
        duree_min: parseInt(data.get('duree_min'), 10) || 120, diplomante: dip,
        diplome: dip ? data.get('diplome') : null,
        capacites: dip ? [...byId('corpus-caps').querySelectorAll('input:checked')].map(i => i.value) : []},
      sequences: Math.min(12, Math.max(1, parseInt(data.get('sequences'), 10) || 4)),
      autoriser_documents_prives: data.get('autoriser_documents_prives') === 'on'};
  }

  // ------------------------------------------------------------------ écran Supports
  async function refreshSupports() {
    const current = folder;
    const list = await json(corpusUrl());
    if (current !== folder || state.step !== 'supports') return;
    const ready = list.filter(c => c.statut === 'pret');
    byId('supports-form').hidden = !ready.length;
    const empty = byId('supports-empty');
    empty.hidden = Boolean(ready.length);
    if (!ready.length) {
      empty.replaceChildren('Aucun corpus prêt dans ce dossier. ',
        el('a', {href: '#corpus', text: 'Construisez d’abord un corpus dans « Mon corpus »'}), '.');
      byId('supports-list').replaceChildren();
      return;
    }
    if (!ready.some(c => c.id === state.corpus)) state.corpus = ready[0].id;
    byId('supports-corpus').replaceChildren(...ready.map(c => el('option',
      {value: c.id, text: `${c.sujet || c.id} (${dateFr(c.cree_le)})`, selected: c.id === state.corpus})));
    await loadSupports(state.corpus);
  }

  async function loadSupports(cid) {
    const current = folder;
    const [cp, list] = await Promise.all([json(corpusUrl(cid) + '/corpus.json'), json(corpusUrl(cid) + '/supports')]);
    if (current !== folder || state.step !== 'supports' || cid !== state.corpus) return;
    // pendant le suivi, on garde les cases que l'enseignant a décochées
    const unchecked = new Set([...byId('supports-seqs').querySelectorAll('input')].filter(i => !i.checked)
      .map(i => i.value));
    byId('supports-seqs').replaceChildren(...cp.sequences.map((s, i) => el('label', {},
      el('input', {type: 'checkbox', value: String(i + 1), checked: !unchecked.has(String(i + 1))}),
      `${i + 1}. ${s.titre}` + (s.points.length ? '' : ' (aucun point)'))));
    renderSupportsList(cid, list);
    byId('supports-go').disabled = list.some(x => x.statut === 'en_cours');
    stopPolling();
    if (list.some(x => x.statut === 'en_cours')) {
      state.timer = setTimeout(() => loadSupports(cid).catch(error => message(error.message, true)), POLL_MS);
    }
  }

  function renderSupportsList(cid, list) {
    const ul = byId('supports-list');
    if (!list.length) {
      ul.replaceChildren(el('li', {className: 'empty', text: 'Aucun support pour ce corpus : choisissez ci-dessus.'}));
      return;
    }
    ul.replaceChildren(...list.map(s => {
      const li = el('li', {}, el('strong', {text: (s.supports || []).map(x => NOMS[x] || x).join(', ')}), ' ', badge(s.statut),
        el('div', {className: 'meta', text: `Lancé le ${dateFr(s.cree_le)}, séquence(s) ${(s.sequences || []).join(', ')}.`}));
      if (s.statut === 'en_cours') li.append(el('div', {className: 'meta',
        text: 'Production en cours : la fiche, le glossaire et le podcast prennent plusieurs minutes avec un vrai modèle.'}));
      if (s.statut === 'erreur') li.append(el('div', {className: 'alert', text: s.erreur || 'Échec de la production.'}));
      for (const r of s.remarques || []) li.append(el('div', {className: 'meta', text: 'À savoir : ' + r}));
      if (s.statut === 'pret') {
        const path = name => corpusUrl(cid) + '/supports/' + encodeURIComponent(s.id) + '/' + encodeURIComponent(name);
        li.append(el('div', {className: 'file-actions'}, ...(s.fichiers || []).flatMap(name => {
          const label = FICHIERS[name] || name;
          const buttons = [action(label, () => download(path(name), name))];
          if (name.endsWith('.html')) buttons.push(action('Ouvrir pour imprimer', () => openInTab(path(name))));
          return buttons;
        })));
      }
      return li;
    }));
  }

  // ------------------------------------------------------------------ branchements
  byId('corpus-diplomante').addEventListener('change', event => {
    byId('corpus-diplome').hidden = !event.target.checked;
  });
  byId('corpus-referentiel').addEventListener('change', showCaps);

  byId('corpus-form').addEventListener('submit', async event => {
    event.preventDefault();
    const body = demande(event.currentTarget);
    if (!body.demande.sujet) {
      status('corpus-status', 'Indiquez le sujet de la formation.', true);
      return;
    }
    if (body.demande.diplomante && !body.demande.capacites.length) {
      status('corpus-status', 'Formation diplômante : cochez au moins une capacité visée.', true);
      return;
    }
    byId('corpus-go').disabled = true;
    try {
      const started = await json(corpusUrl(), {method: 'POST', body: JSON.stringify(body)});
      state.corpus = started.id;
      status('corpus-status', 'Construction lancée. La liste ci-dessous se met à jour toute seule.');
      await refreshCorpus();
    } catch (error) {
      status('corpus-status', error.message, true);
      byId('corpus-go').disabled = false;
    }
  });

  byId('supports-corpus').addEventListener('change', event => {
    state.corpus = event.target.value;
    byId('supports-seqs').replaceChildren();
    loadSupports(state.corpus).catch(error => message(error.message, true));
  });

  byId('supports-form').addEventListener('submit', async event => {
    event.preventDefault();
    const sequences = [...byId('supports-seqs').querySelectorAll('input:checked')].map(i => parseInt(i.value, 10));
    const supports = [...byId('supports-kinds').querySelectorAll('input:checked')].map(i => i.value);
    if (!sequences.length || !supports.length) {
      status('supports-status', 'Cochez au moins une séquence et un type de support.', true);
      return;
    }
    byId('supports-go').disabled = true;
    try {
      const body = {sequences, supports, avec_modele: new FormData(event.currentTarget).get('avec_modele') === 'on'};
      await json(corpusUrl(state.corpus) + '/supports', {method: 'POST', body: JSON.stringify(body)});
      status('supports-status', 'Production lancée. La liste ci-dessous se met à jour toute seule.');
      await loadSupports(state.corpus);
    } catch (error) {
      status('supports-status', error.message, true);
      byId('supports-go').disabled = false;
    }
  });

  // dossiers.html change le dossier ouvert (liste, création, connexion) sans prévenir : on observe la page
  byId('folders').addEventListener('change', () => {
    state.corpus = '';
    byId('corpus-view').hidden = true;
    show(state.step);
  });
  new MutationObserver(() => show(state.step)).observe(byId('folders'), {childList: true});
  new MutationObserver(() => show(state.step)).observe(byId('workspace'), {attributes: true, attributeFilter: ['hidden']});
  byId('logout').addEventListener('click', () => {
    stopPolling();
    freeImages();
    state.corpus = '';
    for (const id of ['corpus-list', 'supports-list', 'supports-seqs']) byId(id).replaceChildren();
    for (const id of ['corpus-status', 'supports-status']) status(id, '');
    byId('corpus-view').hidden = true;
    byId('corpus-form').reset();
    byId('corpus-diplome').hidden = true;
    show(state.step);
  });
  window.addEventListener('hashchange', () => show(stepFromHash()));
  show(stepFromHash());
})();
