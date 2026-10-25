const OT = require("./static/ot.js");
let graine = 12345;
function rnd() { graine = (graine * 1103515245 + 12345) & 0x7fffffff; return graine / 0x7fffffff; }
function ent(a, b) { return a + Math.floor(rnd() * (b - a + 1)); }
function opAlea(t) {
  if (t.length === 0 || rnd() < 0.55) return OT.ins(ent(0, t.length), "abcdef".slice(0, ent(1, 3)));
  const p = ent(0, t.length - 1); return OT.del(p, ent(1, Math.min(4, t.length - p)));
}
let echecs = 0;
for (let i = 0; i < 200000; i++) {
  const t = "0123456789".slice(0, ent(0, 10));
  const a = opAlea(t), b = opAlea(t);
  const [a2, b2] = OT.croiser([a], [b]);       // a est passe en premier
  const x = OT.appliquerListe(OT.appliquer(t, a), b2);
  const y = OT.appliquerListe(OT.appliquer(t, b), a2);
  if (x !== y) { if (echecs++ < 5) console.log("DIVERGENCE", JSON.stringify({t, a, b, x, y})); }
}
console.log(echecs === 0 ? "OK  200000 paires : les deux ordres donnent le meme texte" : `ECHEC : ${echecs}`);
