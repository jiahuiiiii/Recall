/* Shared by index.html and people.html.

   Extracted rather than copied: the two pages render the same records, and a
   second copy of the tag vocabulary or the subtitle rule would drift the moment
   one page was edited and the other was not. */

function esc(s){ return String(s??"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
/* `esc` is enough for text content, not for an attribute a user can type
   into: a quote in a contact field would close `value="` and the rest of the
   handle would become markup. */
function escAttr(s){ return esc(s).replace(/"/g, "&quot;"); }

const $ = id => document.getElementById(id);

/* What to show under a name. `company`/`role` are empty for most records here
   and that is CORRECT, not a failure: the schema asks for an employer and a job
   title, and a student has neither, so the extractor rightly leaves them null.
   Rendering "no company or role recorded" made a working record look broken.
   Fall back to where you met them, which is the fact that actually exists. */
function subtitle(p){
  const bits = [p.role, p.company].filter(Boolean).join(" at ");
  if (bits) return bits;
  const where = (p.met_at || [])[0];
  return where ? "met at " + where : "";
}

/* Words that describe the SHAPE of a fact rather than a value worth filtering
   by. "studies" is not a tag; "computer science" is. Without this the dropdown
   fills with `lives`, `studies`, `pretty`, `together` -- true of everyone and
   useful to nobody. */
const FILLER = new Set(("a an the this that and or but with without who whom whose which what " +
  "is was are were be been being do does did i me my mine we our us you your he him his " +
  "she her hers they them their at in on of for from to by as also just still there here " +
  "got kept keep very quite super really about around some little lately thing things").split(" "));
const PREDICATE = new Set(("lives live lived works work studies study studying studied is was " +
  "has had likes like plays play speaks went goes joined runs leads teaches does came offered " +
  "wanted said want wants doing did think know knew met meet pretty quite very really smart " +
  "nice chill hungry good great friendly together going").split(" "));

const contentTokens = t => t.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(/\s+/)
  .filter(w => w.length > 1 && !FILLER.has(w));

/* Facets, derived rather than stored. There is no tag field on a record: a
   note is free text ("studies computer science at NUS"), and real keys are the
   `attribute_edge` work that is out of scope. So take phrases that RECUR across
   people -- a detail only one person has cannot group anybody, it is just that
   person under another name. */
function deriveTags(people){
  // Model-assigned tags when they exist: they read the facts and share one
  // vocabulary across people, which is the whole point of a filter. The lexical
  // pass below is the fallback for a graph that has never been tagged.
  const tagged = people.filter(p => (p.tags || []).length);
  if (tagged.length) {
    const owners = new Map();
    for (const p of tagged)
      for (const t of p.tags) {
        if (!owners.has(t)) owners.set(t, new Set());
        owners.get(t).add(p.id);
      }
    return [...owners]
      .sort((a, b) => b[1].size - a[1].size || a[0].localeCompare(b[0]))
      .map(([label, ids]) => ({label, ids}));
  }
  return deriveTagsLexically(people);
}

function deriveTagsLexically(people){
  const owners = new Map();
  const add = (k, id) => { if (!owners.has(k)) owners.set(k, new Set()); owners.get(k).add(id); };
  for (const p of people) {
    for (const m of p.met_at || []) add("met: " + m, p.id);
    for (const n of p.notes || []) {
      const ts = contentTokens(n);
      for (let size = 1; size <= 4; size++)
        for (let i = 0; i + size <= ts.length; i++) {
          const span = ts.slice(i, i + size);
          if (PREDICATE.has(span[0]) || PREDICATE.has(span[span.length - 1])) continue;
          add(span.join(" "), p.id);
        }
    }
  }
  const kept = [...owners].filter(([, ids]) => ids.size >= 2);
  const same = (a, b) => a.size === b.size && [...a].every(x => b.has(x));
  // Keep only maximal phrases: "computer science" is worth offering, "computer"
  // is not when it covers exactly the same people.
  return kept
    .filter(([k, ids]) => !kept.some(([o, oid]) =>
        o !== k && same(ids, oid) && ` ${o} `.includes(` ${k} `)))
    .sort((a, b) => b[1].size - a[1].size || a[0].localeCompare(b[0]))
    .map(([k, ids]) => ({label: k, ids}));
}

function haystack(p){
  // Handles are in here and deliberately NOT in the store's `search` haystack:
  // this one answers "which card am I looking for", that one feeds candidate
  // retrieval for dedupe. Typing a phone number to find someone is a filter;
  // matching people on one would be a resolver claiming two records are the
  // same human because they share a number.
  return [p.name, ...(p.aliases||[]), ...(p.notes||[]), ...(p.met_at||[]),
          p.company, p.role, ...Object.values(p.contacts || {})]
         .filter(Boolean).join(" ").toLowerCase();
}

/* The four ways people at these events actually swap details. Order and keys
   match `recall/contacts.CHANNELS`; the server rejects anything else.

   All four are `type="text"` except the number. `type="url"` would be the
   tempting choice for LinkedIn and is wrong: what gets STORED is the path
   (`in/kang-ling`), which is not a URL, so the field would flag the value the
   server just handed it back as invalid. */
const CONTACT_FIELDS = [
  ["phone",     "Phone",     "+65 9123 4567",     "tel",  "Call"],
  ["instagram", "Instagram", "@handle",           "text", "Open"],
  ["telegram",  "Telegram",  "@handle",           "text", "Open"],
  ["linkedin",  "LinkedIn",  "linkedin.com/in/…", "text", "Open"],
];

/* The arrow at the end of a row. Built from `contact_links` on the payload
   rather than from the handle here, so the page and the store cannot disagree
   about what a stored handle means -- `recall/contacts.py::link` is the only
   implementation. Rendered inert rather than omitted when the field is empty,
   so the row keeps its columns and nothing shifts sideways the moment a handle
   is typed. */
function contactLink(p, key){
  const [, label, , , verb] = CONTACT_FIELDS.find(f => f[0] === key);
  const url = (p.contact_links || {})[key];
  if (!url) return `<span class="clink off" aria-hidden="true">↗</span>`;
  return `<a class="clink" href="${escAttr(url)}" target="_blank" rel="noopener noreferrer"
             title="${verb} ${esc(p.name)}"
             aria-label="${verb} ${esc(p.name)}${key === "phone" ? "" : " on " + label}">↗</a>`;
}

/* Always rendered, unlike the other sections: this one is an editor, and a
   record with no handles yet is exactly the record you want to add one to.
   Hiding it when empty would leave no way to fill it in. */
function contactSection(p){
  const have = p.contacts || {};
  const rows = CONTACT_FIELDS.map(([key, label, hint, type]) => `<div class="crow">
      <label class="clab" for="c_${key}">${label}</label>
      <input class="ctl cin" id="c_${key}" data-ch="${key}" type="${type}"
             value="${escAttr(have[key] || "")}" placeholder="${escAttr(hint)}"
             autocomplete="off" autocapitalize="off" spellcheck="false">
      ${contactLink(p, key)}
    </div>`).join("");
  // No Save button. Everything else in this panel lands as you do it -- the ×
  // on a note deletes it there and then -- so a form-style Save was a second,
  // competing idea of what "done" means, and the only thing that made closing
  // the dialog able to lose work. The hint replaces what the button was
  // actually communicating: that these edits persist.
  return `<div class="dsec"><h4>How to reach them</h4>${rows}
    <p class="chint">Saved when you leave a field.</p></div>`;
}


/* ---------- the person record, as a floating dialog ----------

   Both pages open the same record, so the panel lives here rather than in
   either one. It used to be a box appended under the sidebar column, which had
   two problems: on /people it did not exist at all (a card linked back to
   `/?person=<id>` and navigated away from whatever filter you had set), and in
   the sidebar a record with a dozen notes pushed the page taller than the
   viewport, so opening one scrolled the thing you clicked off screen.

   A dialog also makes the modality honest. Merging and forgetting are
   irreversible and both live in here; a panel that shares the page with the
   record list invites a stray click on another name mid-confirm. */

let selectedId = null;
let lastOpener = null;

/* Supplied by the page: where the records live, and how to re-read them after
   this panel changes one. The two pages hold them differently -- index.html
   keys a map by id, /people keeps a sorted array -- and neither shape is worth
   forcing on the other. */
const PersonPanel = { people: () => [], reload: async () => {} };

function configurePersonPanel(hooks){ Object.assign(PersonPanel, hooks); }

function personById(id){ return PersonPanel.people().find(p => p.id === id) || null; }

/* How many OCCASIONS, not how many places. `met_at` is a deduplicated set of
   locations -- and merge consolidates it further, collapsing two descriptions
   of one occasion into the fullest one -- so three memos about the same person
   at the same hall leave one entry, which is why the card used to read
   "1 meeting" no matter how often you recorded someone. Records written before
   the counter existed have no `times_met`; fall back to the number of places
   rather than claiming 0. */
function timesMet(p){
  const n = Number(p.times_met);
  return Number.isFinite(n) && n > 0 ? n : Math.max(1, (p.met_at || []).length);
}
function metLabel(p){
  const n = timesMet(p);
  return n === 1 ? "met once" : `met ${n} times`;
}

/* Notes grouped by the day they were first recorded. They used to render as a
   flat list labelled "memo 1..N" off the ARRAY INDEX -- so twelve notes from
   two memos claimed to be twelve separate occasions, which is what made a
   record look like unrelated fragments. `note_log` carries the date; older
   records without one fall back to a single undated group. */
function groupNotes(p){
  const log = Array.isArray(p.note_log) ? p.note_log : [];
  const at = new Map(log.filter(e => e && e.text).map(e => [e.text, e.at || ""]));
  const order = [], byDay = new Map();
  (p.notes || []).forEach((n, i) => {
    const d = at.get(n) || "";
    if (!byDay.has(d)) { byDay.set(d, []); order.push(d); }
    byDay.get(d).push({ text: n, i });     // keep i: the delete button indexes `notes`
  });
  order.sort();                            // ISO dates sort chronologically; "" first
  return order.map(d => ({ day: d, items: byDay.get(d) }));
}

function dayLabel(d){
  if (!d) return "recorded earlier";
  const t = new Date(d + "T00:00:00");
  return isNaN(t) ? d : t.toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" });
}

/* Built here, not in either page's markup, so neither can drift from the other
   or forget the scrim. */
function panelRoot(){
  let root = $("pmodal");
  if (root) return root;
  root = document.createElement("div");
  root.id = "pmodal";
  root.className = "pmodal hidden";
  root.innerHTML = `<div class="pscrim" data-close="1"></div>
    <div class="pdialog" role="dialog" aria-modal="true" aria-labelledby="dname" tabindex="-1">
      <div id="pdetail"></div>
    </div>`;
  document.body.appendChild(root);
  root.querySelector(".pscrim").onclick = closePerson;
  return root;
}

/* Escape closes, and it is bound once on the document rather than on the dialog:
   focus can legitimately sit on a <select> inside, and a keydown handler on the
   dialog misses nothing but is easy to lose on a re-render. */
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && selectedId) { e.stopPropagation(); closePerson(); }
});

/* Commits whatever is typed in the contact fields but not yet sent. Replaced
   each time the panel renders; a no-op when nothing changed.

   It exists because removing a focused input from the DOM does not reliably
   fire `change`, so Escape and the scrim -- which tear the dialog down -- would
   otherwise drop the field the user was still in. Flushing beats warning: a
   handle is trivially re-typed if it lands wrong, and a confirm dialog to
   protect four short strings is worse than the loss it prevents. */
let flushContacts = async () => {};

/* `keep` means "the record changed underneath an open panel": re-render in
   place, do not steal focus back or re-record who opened it. */
function showPerson(id, keep){
  const p = personById(id);
  if (!p) return;
  if (!keep) lastOpener = document.activeElement;
  selectedId = id;

  document.querySelectorAll(".pcard").forEach(b => {
    const on = b.dataset.id === id;
    b.classList.toggle("sel", on);
    b.setAttribute("aria-expanded", String(on));
  });

  const enr = p.enrichment && !String(p.enrichment).startsWith("NO RELIABLE") ? p.enrichment : "";
  const sec = (title, inner) => inner ? `<div class="dsec"><h4>${title}</h4>${inner}</div>` : "";
  const root = panelRoot();

  $("pdetail").innerHTML = `
    <button class="x" id="dclose" aria-label="Close">×</button>
    <h3 id="dname">${esc(p.name)}</h3>
    <div class="dmeta">${[subtitle(p), metLabel(p), `first seen ${p.first_seen||"?"}`,
        `last seen ${p.last_seen||"?"}`].filter(Boolean).map(esc).join(" · ")}</div>
    <div class="dbody">
    ${sec("Also known as", (p.aliases || []).length
        ? `<div class="note-item"><span class="txt">${p.aliases.map(esc).join(" · ")}</span></div>` : "")}
    ${contactSection(p)}
    ${sec(`What you recorded (${(p.notes||[]).length})`,
        groupNotes(p).map(g => `<div class="ngroup">
          <div class="nday">${esc(dayLabel(g.day))} · ${g.items.length} note${g.items.length===1?"":"s"}</div>
          ${g.items.map(({text,i}) => `<div class="note-item">
            <span class="txt">${esc(text)}</span>
            <button class="xbtn" data-kind="notes" data-i="${i}" title="Delete this note"
                    aria-label="Delete note ${i+1}">×</button>
          </div>`).join("")}
        </div>`).join(""))}
    ${sec(`Where you met (${(p.met_at||[]).length} place${(p.met_at||[]).length===1?"":"s"})`,
        (p.met_at||[]).map((m,i) => `<div class="note-item">
          <span class="txt">${esc(m)}</span>
          <button class="xbtn" data-kind="met_at" data-i="${i}" title="Delete this entry"
                  aria-label="Delete place ${i+1}">×</button>
        </div>`).join(""))}
    ${sec("Public background", enr ? "<ul class=\"facts\">" + enr.split("\n").filter(l=>l.trim())
        .map(l=>`<li>${esc(l.replace(/^[-*\s]+/,""))}</li>`).join("") + "</ul>" : "")}
    ${sec("Same person as", `<div class="mergerow">
      <span class="selwrap"><select class="ctl" id="dmergesel" aria-label="Merge this person into">
        <option value="">Choose someone…</option>
        ${PersonPanel.people().filter(o => o.id !== p.id)
          .map(o => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("")}
      </select></span>
      <button class="btn tiny" id="dmerge">Merge</button>
    </div>`)}
    </div>
    <div class="dactions">
      <button class="danger" id="dforget">Forget this person</button>
      <span class="note" id="dstatus" style="margin:0"></span>
    </div>`;

  root.classList.remove("hidden");
  document.documentElement.classList.add("modal-open");
  $("dclose").onclick = closePerson;
  $("pdetail").querySelectorAll(".xbtn").forEach(b => {
    b.onclick = () => removeEntry(p.id, b.dataset.kind, Number(b.dataset.i));
  });
  armForget(p);
  armMerge(p);
  armContacts(p);
  if (!keep) root.querySelector(".pdialog").focus();
}

function closePerson(){
  // Fire and forget: the dialog is going away, so there is nothing left to
  // report to, and a commit that matches what is stored costs no request.
  flushContacts();
  flushContacts = async () => {};
  selectedId = null;
  const root = $("pmodal");
  if (root) { root.classList.add("hidden"); $("pdetail").innerHTML = ""; }
  document.documentElement.classList.remove("modal-open");
  document.querySelectorAll(".pcard").forEach(b => {
    b.classList.remove("sel"); b.setAttribute("aria-expanded","false");
  });
  // Back to the card that opened it. Without this, closing drops focus on
  // <body> and a keyboard user restarts from the top of the page.
  if (lastOpener && document.contains(lastOpener)) lastOpener.focus();
  lastOpener = null;
}

/* Re-read the graph after this panel changed it, then re-render the open record
   -- or close, if the record it was showing is the one that just went away. */
async function afterChange(){
  // Before the reload, because the re-render below rebuilds the contact inputs
  // -- a handle typed but not yet left would go with them otherwise.
  await flushContacts();
  await PersonPanel.reload();
  if (selectedId && personById(selectedId)) showPerson(selectedId, true);
  else closePerson();
}

/* Deleting one note or meeting place: send the whole shortened list, because
   the store accumulates on upsert and would otherwise re-add what was removed. */
async function removeEntry(id, kind, index){
  const p = personById(id);
  if (!p) return;
  const next = (p[kind] || []).filter((_, i) => i !== index);
  try {
    const r = await fetch(`/api/people/${encodeURIComponent(id)}`, {
      method: "PATCH", headers: {"content-type": "application/json"},
      body: JSON.stringify({[kind]: next})
    });
    if (!r.ok) throw new Error(await readError(r));
    p[kind] = next;
    await afterChange();
  } catch (e) { setStatus("Could not delete: " + e.message); }
}

/* Turn a failed response into something that names the cause. Reading only
   `j.error` swallowed FastAPI's own `detail`, so hitting a route the running
   server did not have yet -- a stale process after an edit -- surfaced as
   "merge failed", which points at the merge rather than at the server. */
async function readError(r){
  let body = {};
  try { body = await r.json(); } catch { /* not JSON: status is all we have */ }
  const why = body.error || (typeof body.detail === "string" ? body.detail
              : Array.isArray(body.detail) ? body.detail.map(d => d.msg).join("; ") : "");
  if (r.status === 404 && why === "Not Found") {
    return "this server does not have that endpoint — restart it to pick up code changes";
  }
  return why ? `${why} (HTTP ${r.status})` : `HTTP ${r.status}`;
}

/* Merging says "these two are the same human" -- the correction the graph
   cannot make for itself. `delete` alone cannot express it: it just loses one
   of the duplicates and its notes.

   Two clicks, like forgetting, because it destroys a record. The absorbed
   person's NAME becomes an alias on the survivor, which is the part that
   matters: without it the merge only tidies the display, and the next memo
   using that name files the duplicate again. */
function armMerge(p){
  const btn = $("dmerge"), sel = $("dmergesel");
  if (!btn || !sel) return;
  let armed = false;
  const reset = () => { armed = false; btn.textContent = "Merge"; btn.classList.remove("armed"); };
  sel.onchange = () => { reset(); setStatus(""); };
  btn.onclick = async () => {
    const targetId = sel.value;
    if (!targetId) { setStatus("Pick who this person really is."); return; }
    const target = personById(targetId);
    if (!armed) {
      armed = true;
      btn.textContent = "Confirm";
      btn.classList.add("armed");
      setStatus(`Fold ${p.name} into ${target.name}? "${p.name}" becomes an alias. This cannot be undone.`);
      setTimeout(() => { if (armed) { reset(); setStatus(""); } }, 5000);
      return;
    }
    try {
      const r = await fetch(`/api/people/${encodeURIComponent(targetId)}/merge`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({source_id: p.id}),
      });
      if (!r.ok) throw new Error(await readError(r));
      const j = await r.json();
      selectedId = targetId;          // follow the survivor, not the record just destroyed
      await afterChange();
      setStatus(`Merged into ${j.name}. Now also known as: ${(j.aliases||[]).join(", ") || "—"}`);
    } catch (e) { setStatus("Could not merge: " + e.message); }
  };
}

/* Contact details, committed when a field is left or Enter is pressed.

   One PATCH carrying all four channels even though one changed, because an
   omitted channel is how the patch says "cleared" -- there is no other way to
   delete a number in a request whose absent fields mean "leave alone".

   **It does not re-render the panel.** Everything else in here does, via
   `afterChange`, and that is exactly wrong for a commit fired by leaving a
   field: rebuilding the inputs would yank focus out of the one the user just
   tabbed INTO. So the rows are updated in place, and the record the page holds
   is updated with them -- nothing on the cards shows a handle, so there is
   nothing else to redraw. */
function armContacts(p){
  const inputs = [...$("pdetail").querySelectorAll(".cin")];
  if (!inputs.length) return;
  const current = () => Object.fromEntries(inputs.map(i => [i.dataset.ch, i.value.trim()]));
  let sent = JSON.stringify(current());

  const commit = async () => {
    const now = current();
    if (JSON.stringify(now) === sent) return;
    sent = JSON.stringify(now);
    try {
      const r = await fetch(`/api/people/${encodeURIComponent(p.id)}`, {
        method: "PATCH", headers: {"content-type": "application/json"},
        body: JSON.stringify({contacts: now})
      });
      if (!r.ok) throw new Error(await readError(r));
      const j = await r.json();
      p.contacts = j.contacts || {};
      p.contact_links = j.contact_links || {};
      redrawContacts(p, inputs);
      // What the server stored, not what was typed: normalisation rewrites a
      // pasted URL into a handle, and without this the next commit would send
      // the raw text again as if it were a fresh edit.
      sent = JSON.stringify(current());
      const n = Object.keys(p.contacts).length;
      setStatus(n ? `Saved — ${n} way${n === 1 ? "" : "s"} to reach ${p.name}.`
                  : `Saved — no contact details for ${p.name}.`);
    } catch (e) {
      sent = "";        // failed, so let the next commit retry instead of assuming it landed
      setStatus("Could not save contact details: " + e.message);
    }
  };

  inputs.forEach(i => {
    // `change`, not `input`: it fires on blur and on Enter, and only when the
    // value actually differs from what was there on focus. That is precisely
    // "the user is done with this field", and it means no request per keystroke.
    i.addEventListener("change", commit);
    i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); i.blur(); } });
  });
  flushContacts = commit;
}

/* Put the stored values back into the rows after a commit. The field the user
   is currently in is left alone -- it is the one they moved to, already in
   sync, and rewriting under a cursor is how an editor loses trust. */
function redrawContacts(p, inputs){
  for (const input of inputs) {
    const key = input.dataset.ch;
    if (input !== document.activeElement) input.value = (p.contacts || {})[key] || "";
    const arrow = input.closest(".crow").querySelector(".clink");
    if (arrow) arrow.outerHTML = contactLink(p, key);
  }
}

/* Two-step confirm. Forgetting someone is irreversible and the button sits
   right under a list of × buttons, so a single stray click must not do it. */
function armForget(p){
  const btn = $("dforget");
  if (!btn) return;
  let armed = false;
  btn.onclick = async () => {
    if (!armed) {
      armed = true;
      btn.textContent = `Really forget ${p.name}?`;
      btn.classList.add("armed");
      setStatus("Click again to confirm. This cannot be undone.");
      setTimeout(() => {
        if (!armed) return;
        armed = false;
        btn.textContent = "Forget this person";
        btn.classList.remove("armed");
        setStatus("");
      }, 5000);
      return;
    }
    try {
      const r = await fetch(`/api/people/${encodeURIComponent(p.id)}`, {method: "DELETE"});
      if (!r.ok) throw new Error(await readError(r));
      closePerson();
      await PersonPanel.reload();
    } catch (e) { setStatus("Could not forget: " + e.message); }
  };
}

function setStatus(msg){ const e = $("dstatus"); if (e) e.textContent = msg; }

/* /people used to link back to `/?person=<id>`. It opens in place now, but the
   link shape is kept working: a shared or bookmarked URL still lands on the
   record. */
function openPersonFromUrl(){
  const want = new URLSearchParams(location.search).get("person");
  if (want && personById(want)) showPerson(want);
}
