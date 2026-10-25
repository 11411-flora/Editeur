globalThis.OT = require("./static/ot.js");
const ClientCollab = require("./static/client.js");
const OT = globalThis.OT;

let graine = Number(process.argv[2] || 7);
function rnd() { graine = (graine * 1103515245 + 12345) & 0x7fffffff; return graine / 0x7fffffff; }
function ent(a, b) { return a + Math.floor(rnd() * (b - a + 1)); }

// "serveur" : meme logique que doc.py
class Serveur {
  constructor() { this.texte = ""; this.journal = []; this.soumissions = []; }
  soumettre(op, base) {
    if (base < 0 || base > this.journal.length) throw new Error("version inconnue");
    this.soumissions.push({ op, base });
    let ops = [op];
    for (const deja of this.journal.slice(base)) {
      ops = OT.croiser([deja], ops)[1];     // deja est passee avant nous : elle gagne les egalites
    }
    for (const o of ops) {
      const ok = o.kind === "ins" ? (o.text !== "" && o.pos >= 0 && o.pos <= this.texte.length)
                                  : (o.length > 0 && o.pos >= 0 && o.pos + o.length <= this.texte.length);
      if (!ok) throw new Error("operation invalide " + JSON.stringify(o));
      this.texte = OT.appliquer(this.texte, o);
    }
    this.journal.push(...ops);
    return [ops, this.journal.length];
  }
}

function simulation(nClients, nActions) {
  const srv = new Serveur();
  const evenements = [];                 // file d'evenements : {t, run}
  let compteur = 0;                      // numero croissant : l'ordre d'envoi est conserve
  let horloge = 0;
  const dernier = new Map();             // un canal garde l'ordre (FIFO)
  function livrer(canal, run) {
    const t = Math.max((dernier.get(canal) || 0) + 1e-6, horloge + rnd() * 30);
    dernier.set(canal, t); evenements.push({ t, run, n: compteur++ });
  }
  let ackIncoherents = 0;
  const clients = [];
  for (let i = 0; i < nClients; i++) {
    const c = new ClientCollab(
      (msg) => livrer("c" + i + ">s", () => traiter(i, msg)),
      { surAck: (msg, enVol) => { if (JSON.stringify(enVol) !== JSON.stringify(msg.ops)) ackIncoherents++; } }
    );
    clients.push(c);
  }
  function traiter(i, msg) {
    if (msg.type !== "op") return;
    const [ops, version] = srv.soumettre(msg.op, msg.base);
    for (let j = 0; j < nClients; j++) {
      if (j === i) livrer("s>c" + j, () => clients[j].recevoir({ type: "ack", version, ops }));
      else if (ops.length) livrer("s>c" + j, () => clients[j].recevoir({ type: "ops", version, ops }));
    }
  }
  for (let i = 0; i < nClients; i++)
    livrer("s>c" + i, () => clients[i].recevoir({ type: "etat", texte: "", version: 0 }));

  // chaque client tape au hasard, a des moments aleatoires
  let nb = 0;
  for (let a = 0; a < nActions; a++) {
    const i = ent(0, nClients - 1);
    const t = a * 5 + rnd() * 20;
    evenements.push({ t, n: compteur++, run: () => {
      const c = clients[i]; if (!c.pret) return;
      const r = rnd();
      if (c.texte.length === 0 || r < 0.5) {            // frappe : on tape parfois plusieurs lettres de suite
        let pos = ent(0, c.texte.length);
        const k = ent(1, 3);
        for (let m = 0; m < k; m++) { c.local(OT.ins(pos, String.fromCharCode(97 + ent(0, 25)))); pos++; }
      } else if (r < 0.75) {                            // collage d'un morceau
        c.local(OT.ins(ent(0, c.texte.length), "<" + ent(0, 99) + ">"));
      } else {                                           // suppression
        const p = ent(0, c.texte.length - 1);
        c.local(OT.del(p, ent(1, Math.min(4, c.texte.length - p))));
      }
      nb++;
    }});
  }
  evenements.sort((x, y) => x.t - y.t || x.n - y.n);
  while (evenements.length) {
    const e = evenements.shift(); horloge = e.t; e.run();
    evenements.sort((x, y) => x.t - y.t || x.n - y.n);
  }
  for (const [i, c] of clients.entries()) {
    if (c.texte !== srv.texte) throw new Error(`client ${i} diverge :\n  ${c.texte}\n  ${srv.texte}`);
    if (c.enVol.length || c.tampon.length || c.enAttente) throw new Error(`client ${i} a encore des modifications en attente`);
  }
  if (ackIncoherents) throw new Error(`${ackIncoherents} acquittements differents de la prediction du client`);
  if (process.env.DUMP) require('fs').appendFileSync(process.env.DUMP, JSON.stringify({ soumissions: srv.soumissions, journal: srv.journal, texte: srv.texte }) + '\n');
  return { versions: srv.journal.length, longueur: srv.texte.length, actions: nb };
}

let total = 0, ops = 0;
for (let s = 0; s < 300; s++) {
  const r = simulation(ent(2, 6), ent(30, 200));
  total++; ops += r.versions;
}
console.log(`OK  ${total} simulations (2 a 6 redacteurs, delais aleatoires, collages, suppressions) : tous convergent, ${ops} operations`);
