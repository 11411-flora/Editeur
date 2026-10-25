// Test de la VRAIE page web (index.html + ot.js + client.js) dans un navigateur simule.
const { JSDOM } = require("jsdom");
const BASE = process.argv[2] || "http://127.0.0.1:8000";
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));
async function jusqua(cond, ms = 5000, pas = 20) {
  for (let t = 0; t < ms; t += pas) { if (await cond()) return true; await attendre(pas); }
  return false;
}
function verifier(cond, msg) { if (!cond) { console.log("ECHEC :", msg); process.exit(1); } }

async function ouvrirPage() {
  return JSDOM.fromURL(BASE + "/", {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(window) { window.fetch = (u, o) => fetch(new URL(u, BASE), o); },
  }).then(async (dom) => { await jusqua(() => dom.window.document.readyState === "complete"); return dom; });
}
function taper(win, valeur) {                       // comme si la personne tapait dans la zone de texte
  const z = win.document.getElementById("zone");
  const debut = z.selectionStart;
  z.value = valeur;
  z.dispatchEvent(new win.Event("input", { bubbles: true }));
}
function inserer(win, pos, texte) {
  const z = win.document.getElementById("zone");
  taper(win, z.value.slice(0, pos) + texte + z.value.slice(pos));
}
async function entrer(dom, nom, email) {
  const d = dom.window.document;
  d.getElementById("nom").value = nom;
  d.getElementById("email").value = email;
  d.getElementById("entrer").click();
  verifier(await jusqua(() => !d.getElementById("vue-app").hidden), "la vue principale n'apparait pas");
}

(async () => {
  const tag = Math.random().toString(36).slice(2, 8);
  const camille = await ouvrirPage();
  verifier(!camille.window.document.getElementById("vue-entree").hidden, "l'ecran d'entree doit etre visible");
  await entrer(camille, "Camille", `camille-${tag}@exemple.fr`);
  const dc = camille.window.document;
  console.log("OK  page chargee, entree avec un nom et un e-mail, credit affiche :", dc.getElementById("credit-texte").textContent);

  dc.getElementById("titre").value = "Edito du journal";
  dc.getElementById("creer").click();
  verifier(await jusqua(() => !dc.getElementById("zone").disabled), "le document ne s'ouvre pas");
  console.log("OK  document cree et ouvert ; liste :", [...dc.querySelectorAll("#liste button")].map((b) => b.textContent).join(", "));

  dc.getElementById("membre").value = `paul-${tag}@exemple.fr`;
  dc.getElementById("inviter").click();
  verifier(await jusqua(() => dc.getElementById("bandeau").textContent.includes("a maintenant accès")), "l'invitation echoue");

  const paul = await ouvrirPage();
  await entrer(paul, "Paul", `paul-${tag}@exemple.fr`);
  const dp = paul.window.document;
  verifier(await jusqua(() => dp.querySelectorAll("#liste button").length === 1), "Paul ne voit pas le document partage");
  dp.querySelector("#liste button").click();
  verifier(await jusqua(() => !dp.getElementById("zone").disabled), "Paul n'arrive pas a ouvrir le document");
  verifier(await jusqua(() => dc.querySelectorAll("#presence li").length === 2 && dp.querySelectorAll("#presence li").length === 2), "la presence n'affiche pas les deux personnes");
  console.log("OK  Paul voit le document partage ; presents :", [...dp.querySelectorAll("#presence li")].map((l) => l.textContent).join(" | "));

  taper(camille.window, "Bonjour tout le monde");
  verifier(await jusqua(() => dp.getElementById("zone").value === "Bonjour tout le monde"), "la frappe de Camille n'arrive pas chez Paul");
  console.log("OK  ce que Camille tape apparait chez Paul");

  // les deux ecrivent en meme temps, a des endroits differents puis au meme endroit
  inserer(camille.window, 0, "[C]");
  inserer(paul.window, 0, "[P]");
  inserer(camille.window, camille.window.document.getElementById("zone").value.length, " fin-C");
  inserer(paul.window, paul.window.document.getElementById("zone").value.length, " fin-P");
  const zc = dc.getElementById("zone"), zp = dp.getElementById("zone");
  verifier(await jusqua(() => zc.value === zp.value && zc.value.includes("[C]") && zc.value.includes("[P]")
                            && zc.value.includes("fin-C") && zc.value.includes("fin-P")), `divergence : "${zc.value}" / "${zp.value}"`);
  console.log("OK  ecriture simultanee, y compris au meme endroit : les deux ecrans sont identiques :", JSON.stringify(zc.value));

  // suppression
  taper(paul.window, zp.value.replace("Bonjour ", ""));
  verifier(await jusqua(() => zc.value === zp.value && !zc.value.includes("Bonjour ")), "la suppression n'est pas propagee");
  console.log("OK  une suppression est propagee");

  // credit et lien
  verifier(await jusqua(() => /restants/.test(dc.getElementById("credit-texte").textContent) && !dc.getElementById("credit-texte").textContent.includes("10000 caractères restants")), "le credit ne diminue pas");
  console.log("OK  le credit diminue a l'ecran :", dc.getElementById("credit-texte").textContent);

  dc.getElementById("max").value = "2";
  dc.getElementById("lien").click();
  verifier(await jusqua(() => dc.querySelectorAll("#liens code").length === 1), "le lien n'est pas affiche");
  const url = dc.querySelector("#liens code").textContent;
  let r = await fetch(url); let n = 0;
  while (r.status === 202) { await attendre(300); r = await fetch(new URL(r.headers.get("location"), BASE)); if (++n > 30) break; }
  verifier(r.status === 200 && (r.headers.get("content-type") || "").includes("pdf"), "le PDF n'est pas livre : " + r.status);
  console.log("OK  le lien affiche donne un PDF :", url);

  camille.window.close(); paul.window.close();
  process.exit(0);
})().catch((e) => { console.log("ERREUR", e); process.exit(1); });
