#!/usr/bin/env python3
"""pe-patch-refresh.py — put the refresh control on a rendered page.

The control sits in the chat header, next to the status dot: one click re-probes for a
Claude session immediately instead of waiting for the four-second poll, and when nothing
answers it asks the local launcher agent to start a bridge for this exploration. A
`file://` page cannot start a process itself; the launcher can, and it is told which
exploration by name, so no path ever leaves the page.

This exists because the reference mock is the source of truth for *new* pages, while the
library already holds rendered ones — and a page in the library is a finished artefact
nobody wants to regenerate to gain a button. Three anchored edits, idempotent:

    pe-patch-refresh.py FILE...        patch in place
    pe-patch-refresh.py --check FILE...  report only, change nothing

A file that already has the control is reported `already` and left alone. A file missing
any anchor is reported `SKIP` with the reason and left alone — never half-patched.
"""
import argparse, os, re, subprocess, sys, tempfile

CSS_ANCHOR = ".dot2.on{background:var(--ok)}.dot2.off{background:var(--muted)}.dot2.busy{background:var(--accent)}"
CSS_ADD = """
/* the refresh control — check for a Claude session, or have one started */
.rfsh{margin-left:6px;width:18px;height:18px;padding:0;flex:none;display:inline-flex;
 align-items:center;justify-content:center;border:1px solid var(--line);border-radius:4px;
 background:#fff;color:var(--muted);font-size:11px;line-height:1;cursor:pointer;
 transition:color .15s,border-color .15s}
.rfsh:hover{color:var(--ink2);border-color:var(--ink2)}
.rfsh:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.rfsh[disabled]{cursor:default;opacity:.55}
.rfsh.spin svg{animation:rfspin .9s linear infinite;transform-origin:50% 50%}
@keyframes rfspin{to{transform:rotate(360deg)}}"""

DOT_ANCHOR = '<span class="dot2" id="chatDot"></span>'
BTN = ('<button type="button" class="rfsh" id="chatRfsh" title="" aria-label="">'
       '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" focusable="false">'
       '<path d="M13.6 8a5.6 5.6 0 1 1-1.64-3.96" fill="none" stroke="currentColor" '
       'stroke-width="1.6" stroke-linecap="round"/>'
       '<path d="M13.9 1.9v3.2h-3.2" fill="none" stroke="currentColor" stroke-width="1.6" '
       'stroke-linecap="round" stroke-linejoin="round"/></svg></button>')

# The focus listener is the insertion point, and the status setter is called from the
# new code — but neither name can be assumed. An early translation pass renamed JS
# identifiers along with the prose (`bridgeState` -> `bridgeStato`,
# `setChatStatus` -> `setChatStato`), so a page in the library may carry either. Both
# are discovered from the file itself; a page whose shape is genuinely unrecognised is
# skipped whole rather than patched with a name that does not exist there.
JS_ANCHOR_RE = re.compile(
    r"^addEventListener\('focus',\(\)=>\{ if\(\w+!=='ready'\) checkBridge\(\); \}\);$", re.M)
SETSTATUS_RE = re.compile(r"^function (setChat\w+)\(state,text,title\)\{", re.M)
JS_ADD = r"""
/* ---- the refresh control: find a session, or have one started ----------------
   The dot reports whether a bridge is answering; this control acts on it. One click
   re-probes at once rather than waiting for the four-second poll. If nothing answers,
   it asks the launcher agent — a small always-on daemon on 127.0.0.1:8790, installed
   by setup.sh — to start a bridge for THIS exploration. The page cannot start a
   process; the launcher can. It is given the exploration's folder NAME, never a path,
   and resolves it inside the library itself, so the page has no say over what runs
   where. With no launcher installed, say so plainly and name the one command that
   fixes it — never spin forever pretending.                                       */
const LAUNCHER='http://127.0.0.1:8790';
const RFSH_T={
 en:{tip:'Check for a Claude session — start one if none is running',
     look:'Looking for a Claude session…',start:'Starting Claude…',
     up:'Claude is up — ask away.',
     none:'No Claude session is running, and no launcher agent is installed to start one. Start it yourself with <code>pe-chat %s</code>, or install the launcher by running the plugin\'s <code>setup.sh</code> once.',
     noc:'The launcher started, but found no <code>claude</code> on <code>PATH</code>.',
     slow:'Claude was asked to start but did not answer in time — see <code>.chat-bridge.log</code> in this exploration\'s folder.'},
 it:{tip:'Cerca una sessione Claude — se non è attiva, la avvia',
     look:'Cerco una sessione Claude…',start:'Avvio di Claude…',
     up:'Claude è attivo — puoi chiedere.',
     none:'Nessuna sessione Claude attiva e nessun agente di avvio installato. Avviala con <code>pe-chat %s</code>, oppure installa l\'agente eseguendo una volta <code>setup.sh</code> del plugin.',
     noc:'L\'agente di avvio è partito, ma non ha trovato <code>claude</code> nel <code>PATH</code>.',
     slow:'Claude è stato avviato ma non ha risposto in tempo — vedi <code>.chat-bridge.log</code> nella cartella di questa esplorazione.'},
 de:{tip:'Nach einer Claude-Sitzung suchen — und sie starten, falls keine läuft',
     look:'Suche nach einer Claude-Sitzung…',start:'Claude wird gestartet…',
     up:'Claude läuft — fragen Sie einfach.',
     none:'Es läuft keine Claude-Sitzung, und es ist kein Start-Agent installiert. Starten Sie sie selbst mit <code>pe-chat %s</code>, oder installieren Sie den Agenten, indem Sie <code>setup.sh</code> des Plugins einmal ausführen.',
     noc:'Der Start-Agent lief, fand aber kein <code>claude</code> im <code>PATH</code>.',
     slow:'Claude sollte starten, hat aber nicht rechtzeitig geantwortet — siehe <code>.chat-bridge.log</code> im Ordner dieser Erkundung.'},
 fr:{tip:'Chercher une session Claude — la démarrer si aucune ne tourne',
     look:'Recherche d\'une session Claude…',start:'Démarrage de Claude…',
     up:'Claude est actif — posez votre question.',
     none:'Aucune session Claude ne tourne, et aucun agent de démarrage n\'est installé. Lancez-la avec <code>pe-chat %s</code>, ou installez l\'agent en exécutant une fois le <code>setup.sh</code> du plugin.',
     noc:'L\'agent de démarrage a démarré, mais n\'a trouvé aucun <code>claude</code> dans le <code>PATH</code>.',
     slow:'Claude a reçu l\'ordre de démarrer mais n\'a pas répondu à temps — voir <code>.chat-bridge.log</code> dans le dossier de cette exploration.'},
 es:{tip:'Buscar una sesión de Claude — iniciarla si no hay ninguna',
     look:'Buscando una sesión de Claude…',start:'Iniciando Claude…',
     up:'Claude está activo — ya puedes preguntar.',
     none:'No hay ninguna sesión de Claude en marcha ni un agente de arranque instalado. Iníciala con <code>pe-chat %s</code>, o instala el agente ejecutando una vez el <code>setup.sh</code> del plugin.',
     noc:'El agente de arranque se inició, pero no encontró <code>claude</code> en el <code>PATH</code>.',
     slow:'Se pidió a Claude que arrancara pero no respondió a tiempo — consulta <code>.chat-bridge.log</code> en la carpeta de esta exploración.'},
 pt:{tip:'Procurar uma sessão do Claude — iniciá-la se nenhuma estiver ativa',
     look:'A procurar uma sessão do Claude…',start:'A iniciar o Claude…',
     up:'O Claude está ativo — pode perguntar.',
     none:'Não há nenhuma sessão do Claude ativa nem um agente de arranque instalado. Inicie-a com <code>pe-chat %s</code>, ou instale o agente executando uma vez o <code>setup.sh</code> do plugin.',
     noc:'O agente de arranque iniciou, mas não encontrou <code>claude</code> no <code>PATH</code>.',
     slow:'O Claude foi mandado arrancar mas não respondeu em tempo — veja <code>.chat-bridge.log</code> na pasta desta exploração.'},
 nl:{tip:'Zoek een Claude-sessie — start er een als er geen loopt',
     look:'Zoeken naar een Claude-sessie…',start:'Claude wordt gestart…',
     up:'Claude is actief — stel je vraag.',
     none:'Er loopt geen Claude-sessie en er is geen start-agent geïnstalleerd. Start hem zelf met <code>pe-chat %s</code>, of installeer de agent door de <code>setup.sh</code> van de plugin één keer uit te voeren.',
     noc:'De start-agent liep, maar vond geen <code>claude</code> op het <code>PATH</code>.',
     slow:'Claude is gevraagd te starten maar antwoordde niet op tijd — zie <code>.chat-bridge.log</code> in de map van deze verkenning.'},
 ar:{tip:'التحقّق من وجود جلسة Claude — وبدؤها إن لم تكن تعمل',
     look:'جارٍ البحث عن جلسة Claude…',start:'جارٍ تشغيل Claude…',
     up:'Claude يعمل الآن — اطرح سؤالك.',
     none:'لا توجد جلسة Claude تعمل، ولا وكيل تشغيل مُثبَّت لبدئها. ابدأها بنفسك عبر <code>pe-chat %s</code>، أو ثبِّت الوكيل بتشغيل <code>setup.sh</code> الخاص بالإضافة مرّة واحدة.',
     noc:'عمل وكيل التشغيل، لكنه لم يجد <code>claude</code> في <code>PATH</code>.',
     slow:'طُلب من Claude أن يبدأ لكنه لم يستجب في الوقت المحدّد — راجع <code>.chat-bridge.log</code> في مجلّد هذا الاستكشاف.'}
};
function rfshT(k){
  const t=(typeof CURRENT_LANG==='string'&&RFSH_T[CURRENT_LANG])?RFSH_T[CURRENT_LANG]:RFSH_T.en;
  return t[k]||RFSH_T.en[k];
}
const rfshWait=ms=>new Promise(r=>setTimeout(r,ms));
/* Used only for the command the reader copies. The launcher is never handed a path —
   it gets a folder name and resolves it itself — but `pe-chat` does need one, and the
   page happens to know exactly where it is sitting. */
const rfshDir=()=>{
  try{ return decodeURIComponent(location.pathname).replace(/\/[^\/]*$/,'')||here().path; }
  catch(e){ return here().path; }
};

/* Ask the launcher to start a bridge for this exploration. Returns the launcher's own
   answer, or {error:'no-launcher'} when nothing is listening on 8790 — which is simply
   what an install without the agent looks like, not a fault to shout about. */
async function askLauncher(){
  let health;
  try{
    const c=new AbortController(); const to=setTimeout(()=>c.abort(),1500);
    health=await (await fetch(LAUNCHER+'/health',{cache:'no-store',signal:c.signal})).json();
    clearTimeout(to);
  }catch(e){ return {error:'no-launcher'}; }
  if(!health||!health.ok) return {error:'no-launcher'};
  if(!health.claude)      return {error:'no-claude'};
  try{
    const r=await fetch(LAUNCHER+'/start',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({exploration:here().path})});
    return await r.json();
  }catch(e){ return {error:'start-failed'}; }
}

let rfshBusy=false;
async function refreshBridge(){
  if(rfshBusy) return;
  rfshBusy=true;
  const btn=document.getElementById('chatRfsh');
  if(btn){ btn.classList.add('spin'); btn.disabled=true; }
  try{
    setChatStatus('busy',rfshT('look'));
    if(await checkBridge({quiet:false})) return;        /* one was already there */
    setChatStatus('busy',rfshT('start'));
    const res=await askLauncher();
    if(res&&res.ok){
      /* The launcher waits for the bridge's own /health before answering, so this
         loop is short — it covers the page's probe, not the process start. */
      for(let i=0;i<10;i++){
        if(await checkBridge({quiet:false})){ sysMsg('filed',rfshT('up')); return; }
        await rfshWait(600);
      }
      sysMsg('sys',rfshT('slow'));
    }else if(res&&res.error==='no-claude'){
      sysMsg('sys',rfshT('noc'));
    }else if(res&&res.error==='unknown-exploration'){
      sysMsg('sys',rfshT('none').replace('%s',rfshDir()));
    }else{
      sysMsg('sys',rfshT('none').replace('%s',rfshDir()));
    }
    await checkBridge();                                /* settle the dot honestly */
  }finally{
    rfshBusy=false;
    if(btn){ btn.classList.remove('spin'); btn.disabled=false; }
  }
}
{ const b=document.getElementById('chatRfsh');
  if(b){ b.title=RFSH_T.en.tip; b.setAttribute('aria-label',RFSH_T.en.tip);
         b.onclick=refreshBridge;
         /* the label is localised once the language constant is readable */
         setTimeout(()=>{ b.title=rfshT('tip'); b.setAttribute('aria-label',rfshT('tip')); },0); } }
"""


def patch(text):
    """Return (new_text, note). note is 'ok', 'already', or 'SKIP <reason>'."""
    if 'id="chatRfsh"' in text:
        return text, "already"
    for anchor, what in ((CSS_ANCHOR, "dot2 css"), (DOT_ANCHOR, "chatDot span")):
        if text.count(anchor) != 1:
            return text, "SKIP %s appears %dx, expected once" % (what, text.count(anchor))
    hits = JS_ANCHOR_RE.findall(text)
    if len(hits) != 1:
        return text, "SKIP focus listener appears %dx, expected once" % len(hits)
    setters = SETSTATUS_RE.findall(text)
    if len(setters) != 1:
        return text, "SKIP status setter appears %dx, expected once" % len(setters)
    js = JS_ADD.strip("\n").replace("setChatStatus(", setters[0] + "(")
    text = text.replace(CSS_ANCHOR, CSS_ANCHOR + CSS_ADD, 1)
    text = text.replace(DOT_ANCHOR, BTN + DOT_ANCHOR, 1)
    text = JS_ANCHOR_RE.sub(lambda m: js + "\n" + m.group(0), text, count=1)
    return text, "ok"


def node_check(text, path):
    """Run every <script> body past `node --check`, the same gate pe-splice.py uses:
    a page that cannot parse is worse than a page with no button."""
    if not any(os.access(os.path.join(d, "node"), os.X_OK)
               for d in os.environ.get("PATH", "").split(os.pathsep) if d):
        return None
    for i, body in enumerate(re.findall(r"<script\b[^>]*>(.*?)</script>", text, re.S)):
        if not body.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(body)
            tmp = f.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode:
                return "script #%d: %s" % (i + 1, (r.stderr or "").strip().splitlines()[0:1])
        finally:
            os.unlink(tmp)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    a = ap.parse_args()
    bad = 0
    for path in a.files:
        try:
            src = open(path, encoding="utf-8").read()
        except OSError as e:
            print("SKIP\t%s\t%s" % (path, e)); bad += 1; continue
        out, note = patch(src)
        if note != "ok":
            print("%s\t%s" % (note.split()[0] if note.startswith("SKIP") else note, path)
                  + ("\t" + note[5:] if note.startswith("SKIP") else ""))
            bad += note.startswith("SKIP")
            continue
        err = node_check(out, path)
        if err:
            print("SKIP\t%s\tJS would not parse: %s" % (path, err)); bad += 1; continue
        if a.check:
            print("would-patch\t%s" % path); continue
        open(path, "w", encoding="utf-8").write(out)
        print("patched\t%s" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
