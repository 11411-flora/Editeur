// Transformation des modifications, cote navigateur.
// Meme logique que doc.py ; en plus, "autreGagne" dit qui passe devant
// quand deux personnes inserent exactement au meme endroit.
(function (racine) {
  function ins(pos, text) { return { kind: "ins", pos: pos, text: text, length: 0 }; }
  function del(pos, length) { return { kind: "del", pos: pos, text: "", length: length }; }

  function appliquer(texte, op) {
    if (op.kind === "ins") return texte.slice(0, op.pos) + op.text + texte.slice(op.pos);
    return texte.slice(0, op.pos) + texte.slice(op.pos + op.length);
  }

  function appliquerListe(texte, ops) {
    for (const o of ops) texte = appliquer(texte, o);
    return texte;
  }

  // op et autre ont ete ecrites sur le MEME texte ; autre est deja appliquee.
  // Renvoie la liste d'operations equivalentes a op, valables APRES autre.
  function transformer(op, autre, autreGagne) {
    if (autreGagne === undefined) autreGagne = true;
    if (op.kind === "ins") {
      if (autre.kind === "ins") {
        const decale = autreGagne ? autre.pos <= op.pos : autre.pos < op.pos;
        return [ins(decale ? op.pos + autre.text.length : op.pos, op.text)];
      }
      const a = autre.pos, n = autre.length;
      let p;
      if (op.pos <= a) p = op.pos;
      else if (op.pos >= a + n) p = op.pos - n;
      else p = a;
      return [ins(p, op.text)];
    }
    if (autre.kind === "ins") {
      const q = autre.pos, u = autre.text.length;
      if (q <= op.pos) return [del(op.pos + u, op.length)];
      if (q >= op.pos + op.length) return [op];
      const gauche = q - op.pos;
      return [del(op.pos, gauche), del(op.pos + u, op.length - gauche)];
    }
    const p = op.pos, n = op.length, q = autre.pos, m = autre.length;
    const chev = Math.max(0, Math.min(p + n, q + m) - Math.max(p, q));
    const reste = n - chev;
    if (reste === 0) return [];
    let nouvelle;
    if (q + m <= p) nouvelle = p - m;
    else if (q >= p + n) nouvelle = p;
    else nouvelle = Math.min(p, q);
    return [del(nouvelle, reste)];
  }

  // a et b : deux listes d'operations ecrites sur le meme texte.
  // "a" a deja ete appliquee en premier (cote serveur) : a gagne les egalites.
  // Renvoie [a', b'] avec  b puis a'  ==  a puis b'.
  function croiser(a, b) {
    if (a.length === 0 || b.length === 0) return [a, b];
    if (a.length > 1) {
      const r1 = croiser([a[0]], b);
      const r2 = croiser(a.slice(1), r1[1]);
      return [r1[0].concat(r2[0]), r2[1]];
    }
    if (b.length > 1) {
      const r1 = croiser(a, [b[0]]);
      const r2 = croiser(r1[0], b.slice(1));
      return [r2[0], r1[1].concat(r2[1])];
    }
    const x = a[0], y = b[0];
    return [transformer(x, y, false), transformer(y, x, true)];
  }

  racine.OT = { ins: ins, del: del, appliquer: appliquer, appliquerListe: appliquerListe,
                transformer: transformer, croiser: croiser };
  if (typeof module !== "undefined") module.exports = racine.OT;
})(typeof window !== "undefined" ? window : globalThis);
