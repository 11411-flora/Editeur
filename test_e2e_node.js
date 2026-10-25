// Test de bout en bout : le VRAI code du navigateur contre le VRAI serveur.
globalThis.OT = require("./static/ot.js");
const ClientCollab = require("./static/client.js");
const OT = globalThis.OT;

const HTTP = process.argv[2] || "http://127.0.0.1:8000";
const WS = HTTP.replace("http", "ws");
const N = Number(process.argv[3] || 8);
const ACTIONS = Number(process.argv[4] || 150);

let graine = 4242;
function rnd() { graine = (graine * 1103515245 + 12345) & 0x7fffffff; return graine / 0x7fffffff; }
function ent(a, b) { return a + Math.floor(rnd() * (b - a + 1)); }
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(methode, chemin, email, corps) {
  const r = await fetch(HTTP + chemin, {
    method: methode,
    headers: { "X-Email": email, "Content-Type": "application/json" },
    body: corps ? JSON.stringify(corps) : undefined,
  });
  return { statut: r.status, json: await r.json().catch(() => null) };
}

function ouvrir(doc, email) {
  return new Promise((resolve) => {
    const ws = new WebSocket(`${WS}/documents/${doc}/live?email=${encodeURIComponent(email)}&nom=${email.split("@")[0]}`);
    const c = new ClientCollab((m) => ws.send(JSON.stringify(m)), {
      surErreur: (m) => { c.erreurs.push(m); },
    });
    c.erreurs = [];
    ws.onmessage = (e) => c.recevoir(JSON.parse(e.data));
    ws.onopen = () => {
      const t = setInterval(() => { if (c.pret) { clearInterval(t); resolve({ c, ws }); } }, 10);
    };
  });
}

const calme = (c) => !c.enAttente && c.tampon.length === 0 && !c.attenteEtat;

async function scenario_collaboration() {
  const tag = Math.random().toString(36).slice(2, 8);
  const emails = Array.from({ length: N }, (_, i) => `n${i}-${tag}@exemple.fr`);
  const doc = (await api("POST", "/documents", emails[0], { titre: "e2e" })).json.id;
  for (const e of emails.slice(1)) await api("POST", `/documents/${doc}/membres`, emails[0], { email: e });
  const clients = await Promise.all(emails.map((e) => ouvrir(doc, e)));

  await Promise.all(clients.map(async ({ c }) => {
    for (let a = 0; a < ACTIONS; a++) {
      await attendre(ent(1, 25));
      const r = rnd();
      if (c.texte.length === 0 || r < 0.55) {
        let pos = ent(0, c.texte.length);
        const k = ent(1, 3);
        for (let m = 0; m < k; m++) { c.local(OT.ins(pos, String.fromCharCode(97 + ent(0, 25)))); pos++; }
      } else if (r < 0.7) {
        c.local(OT.ins(ent(0, c.texte.length), "<" + ent(0, 99) + ">"));
      } else {
        const p = ent(0, c.texte.length - 1);
        c.local(OT.del(p, ent(1, Math.min(4, c.texte.length - p))));
      }
    }
  }));

  // on attend que tout le monde ait fini d'envoyer et de recevoir
  for (let i = 0; i < 400 && !clients.every(({ c }) => calme(c)); i++) await attendre(25);
  await attendre(400);
  const serveur = (await api("GET", `/documents/${doc}`, emails[0])).json;
  const divergents = clients.map(({ c }, i) => [c, i]).filter(([c]) => c.texte !== serveur.texte || c.version !== serveur.version);
  const erreurs = clients.reduce((s, { c }) => s + c.erreurs.length, 0);
  clients.forEach(({ ws }) => ws.close());
  if (divergents.length || erreurs) {
    console.log("ECHEC", { divergents: divergents.map(([, i]) => i), erreurs, serveur: serveur.texte.slice(0, 80) });
    process.exit(1);
  }
  console.log(`OK  ${N} navigateurs (vrai ot.js + client.js) x ${ACTIONS} actions simultanees : tous identiques au serveur ` +
              `(version ${serveur.version}, ${serveur.texte.length} caracteres)`);
}

async function scenario_credit_epuise() {
  const tag = Math.random().toString(36).slice(2, 8);
  const email = `riche-${tag}@exemple.fr`;
  const doc = (await api("POST", "/documents", email, { titre: "credit" })).json.id;
  await api("POST", `/documents/${doc}/ops`, email, { base: 0, op: { kind: "ins", pos: 0, text: "a".repeat(10000) } });
  const { c, ws } = await ouvrir(doc, email);
  c.local(OT.ins(0, "zzz"));                  // refuse : le credit du jour est epuise
  for (let i = 0; i < 100 && !(c.erreurs.length && calme(c)); i++) await attendre(20);
  const serveur = (await api("GET", `/documents/${doc}`, email)).json;
  ws.close();
  if (!c.erreurs.length || c.erreurs[0].code !== 429 || c.texte !== serveur.texte) {
    console.log("ECHEC credit", c.erreurs, c.texte.length, serveur.texte.length); process.exit(1);
  }
  console.log("OK  credit epuise : le navigateur recoit l'erreur 429, puis retrouve le texte officiel (la frappe refusee disparait)");
}

(async () => { await scenario_collaboration(); await scenario_credit_epuise(); process.exit(0); })();
