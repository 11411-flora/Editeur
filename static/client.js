// Le "cerveau" du navigateur : il ne touche pas a la page, il gere seulement
// l'etat. La page lui donne ce que tape l'utilisateur et lui transmet ce que
// dit le serveur. Un seul envoi a la fois (enVol) ; le reste attend (tampon).
(function (racine) {
  const OT = racine.OT;

  class ClientCollab {
    constructor(envoyer, rappels) {
      this.envoyer = envoyer;            // fonction : envoie un message au serveur
      this.rappels = rappels || {};      // surEtat, surOps, surErreur, surPresence, surAck
      this.texte = "";
      this.version = 0;
      this.enVol = [];                   // envoye, pas encore acquitte
      this.tampon = [];                  // tape, pas encore envoye
      this.attenteEtat = false;
      this.enAttente = false;            // vrai tant qu'on attend l'accuse de l'envoi en cours
      this.pret = false;
    }

    // L'utilisateur vient de taper : une modification locale, deja visible a l'ecran.
    local(op) {
      if (this.attenteEtat) return;      // on attend l'etat officiel : l'ecran sera remplace
      this.texte = OT.appliquer(this.texte, op);
      const der = this.tampon[this.tampon.length - 1];
      if (der && der.kind === "ins" && op.kind === "ins" && op.pos === der.pos + der.text.length) {
        this.tampon[this.tampon.length - 1] = OT.ins(der.pos, der.text + op.text);   // frappes collees
      } else {
        this.tampon.push(op);
      }
      this._envoyerSuivant();
    }

    recevoir(msg) {
      const r = this.rappels;
      if (msg.type === "etat") {
        this.texte = msg.texte; this.version = msg.version;
        this.enVol = []; this.tampon = []; this.attenteEtat = false; this.enAttente = false; this.pret = true;
        if (r.surEtat) r.surEtat(msg);
      } else if (msg.type === "ops") {
        if (this.attenteEtat) return;    // deja compris dans l'etat qui arrive
        for (const o of msg.ops) {
          let x = OT.croiser([o], this.enVol);  const o1 = x[0]; this.enVol = x[1];
          x = OT.croiser(o1, this.tampon);      const o2 = x[0]; this.tampon = x[1];
          this.texte = OT.appliquerListe(this.texte, o2);
          if (r.surOps) r.surOps(o2);
        }
        this.version = msg.version;
      } else if (msg.type === "ack") {
        if (this.attenteEtat) return;
        if (r.surAck) r.surAck(msg, this.enVol);
        this.enVol = []; this.enAttente = false; this.version = msg.version;
        this._envoyerSuivant();
      } else if (msg.type === "erreur") {
        this.attenteEtat = true; this.enVol = []; this.tampon = []; this.enAttente = false;
        this.envoyer({ type: "sync" });
        if (r.surErreur) r.surErreur(msg);
      } else if (msg.type === "presence") {
        if (r.surPresence) r.surPresence(msg);
      }
    }

    _envoyerSuivant() {
      if (!this.enAttente && this.tampon.length > 0 && !this.attenteEtat) {
        this.enAttente = true;
        this.enVol = [this.tampon.shift()];
        this.envoyer({ type: "op", base: this.version, op: this.enVol[0] });
      }
    }
  }

  racine.ClientCollab = ClientCollab;
  if (typeof module !== "undefined") module.exports = ClientCollab;
})(typeof window !== "undefined" ? window : globalThis);
