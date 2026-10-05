"use client";
import { useRef, useState } from "react";
import { FileUp, Plus, Search } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { api, downloadImportTemplate, downloadSubscribersExport, importSubscribers, type ImportResult } from "@/services/api";
import { dateTime } from "@/lib/utils";
import { TYPE_LABELS, type Application } from "@/types";
import { useAuth } from "./auth-provider";
import { Empty, ErrorBox, Loading, PageTitle, StatusBadge } from "./common";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";

type Account = {
  id: number; account_number: string; meter_number: string; full_name: string;
  address: string; phone: string | null; active: boolean; telegram_user_id: number | null;
  binding_note: string | null; version: number; last_reading: string | number | null; last_period: string | null;
};
type Reading = {
  id: string; account_number: string; meter_number: string; full_name: string; period: string;
  value: string | number | null; consumption: string | number | null; last_reading: string | number | null;
  status: "PENDING" | "ACCEPTED" | "REJECTED"; review_note: string | null;
};
type RegistryStats = { period: string; total: number; accepted: number; pending: number; missing: number };
type Profile = {
  account: Account; readings: Reading[]; applications: Application[];
  history: { action: string; admin_name: string; created_at: string }[];
};
const readingLabels = { PENDING: "Тексерілуде", ACCEPTED: "Қабылданды", REJECTED: "Қабылданбады" };
const formatPeriod = (iso: string) => `${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

function ReviewForm({ reviewing, busy, error, onSubmit }: {
  reviewing: Reading; busy: boolean; error: string; onSubmit: (body: unknown) => void;
}) {
  const [status, setStatus] = useState<"ACCEPTED" | "REJECTED">("ACCEPTED");
  return <form className="form-stack" onSubmit={(e) => {
    e.preventDefault(); const form = new FormData(e.currentTarget);
    onSubmit({ status, note: String(form.get("note")), value: status === "ACCEPTED" ? String(form.get("value")) : null });
  }}>
    <p>Шот: {reviewing.account_number} · {formatPeriod(reviewing.period)}</p>
    <img className="lightbox-image" src={`/api/subscribers/readings/${reviewing.id}/photo`} alt="Есептегіштің фотосы" />
    <p>Соңғы қабылданған: {reviewing.last_reading ?? "Жоқ — бастапқы мән"}</p>
    <label>Шешім<select name="status" value={status} onChange={(e) => setStatus(e.target.value as "ACCEPTED" | "REJECTED")}>
      <option value="ACCEPTED">Қабылдау</option><option value="REJECTED">Қабылдамау</option></select></label>
    {status === "ACCEPTED" && <label>Фотодан оқылған көрсеткіш (м³)<input name="value" type="number" inputMode="decimal"
      step="0.001" min="0" max="99999999999" required /></label>}
    <label>Түсініктеме<textarea name="note" required minLength={3} maxLength={500} /></label>
    <ErrorBox message={error} /><Button type="submit" disabled={busy}>Шешімді сақтау</Button>
  </form>;
}

function ImportDialog({ open, busy, onClose, onImported }: {
  open: boolean; busy: boolean; onClose: () => void; onImported: () => void;
}) {
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = inputRef.current?.files?.[0];
    if (!file) return;
    setSubmitting(true); setError(""); setResult(null);
    try {
      const imported = await importSubscribers(file);
      setResult(imported);
      onImported();
    } catch (err) { setError((err as Error).message); }
    finally { setSubmitting(false); }
  }

  return <Dialog open={open} onOpenChange={(next) => { if (!next && !busy && !submitting) { setResult(null); setError(""); onClose(); } }}>
    <DialogContent title="Файлдан абонент қосу"
      description="Тек .xlsx немесе .csv файл. Бірінші жол — тақырыптар (Дербес шот, Есептегіш нөмірі, Аты-жөні, Мекенжай, Телефон). Формулалары бар ұяшықтар қабылданбайды.">
      <form className="form-stack" onSubmit={submit}>
        <Button type="button" variant="outline" onClick={() => void downloadImportTemplate()}>Үлгіні жүктеп алу</Button>
        <label>Файл<input ref={inputRef} name="file" type="file" accept=".xlsx,.csv" required /></label>
        <ErrorBox message={error} />
        <Button type="submit" disabled={submitting}>{submitting ? "Жүктелуде…" : "Импорттау"}</Button>
      </form>
      {result && <div className="section-note">
        <p>Қосылды: <strong>{result.created}</strong> / {result.total}</p>
        {result.skipped.length > 0 && <><p>Өткізіп жіберілді (бұрыннан тіркелген):</p>
          <ul>{result.skipped.map((s) => <li key={s.line}>{s.line}-жол: {s.reason}</li>)}</ul></>}
        {result.errors.length > 0 && <><p>Қателер:</p>
          <ul>{result.errors.map((e) => <li key={e.line}>{e.line}-жол: {e.reason}</li>)}</ul></>}
      </div>}
    </DialogContent>
  </Dialog>;
}

function ProfileDialog({ accountId, onClose }: { accountId: number | null; onClose: () => void }) {
  const profile = useApi<Profile>(accountId ? `/subscribers/${accountId}/profile` : null);
  const p = profile.data;
  return <Dialog open={accountId !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent title="Абонент профилі" wide
      description={p ? `${p.account.account_number} · ${p.account.full_name} · ${p.account.address}` : ""}>
      {profile.loading ? <Loading /> : !p ? <ErrorBox message={profile.error} /> : <div className="form-stack">
        <section>
          <h3>Газ көрсеткіштері <span className="count-chip">{p.readings.length}</span></h3>
          {p.readings.length === 0 ? <p className="section-note">Әзірге жіберілген көрсеткіш жоқ.</p> :
            <ul>{p.readings.map((r) => <li key={r.id}>
              {formatPeriod(r.period)} — {r.value === null ? "Тексерілуде" : `${r.value} м³`}
              {r.consumption !== null && ` (шығын: ${r.consumption} м³)`} · {readingLabels[r.status]}
            </li>)}</ul>}
        </section>
        <section>
          <h3>Өтінімдер <span className="count-chip">{p.applications.length}</span></h3>
          {p.applications.length === 0 ? <p className="section-note">Әзірге өтінім жоқ.</p> :
            <ul>{p.applications.map((a) => <li key={a.id}>
              {a.application_number} — {TYPE_LABELS[a.application_type]} · <StatusBadge status={a.status} />{" "}
              <small>{dateTime(a.created_at)}</small>
            </li>)}</ul>}
        </section>
        <section>
          <h3>Тарих</h3>
          {p.history.length === 0 ? <p className="section-note">Жазба жоқ.</p> :
            <ul>{p.history.map((h, i) => <li key={i}>
              <small>{dateTime(h.created_at)}</small> — {h.action} ({h.admin_name})
            </li>)}</ul>}
        </section>
      </div>}
    </DialogContent>
  </Dialog>;
}

export function Subscribers({ revision }: { revision: number }) {
  const { admin } = useAuth();
  const allowed = admin?.role === "SUPER_ADMIN";
  const [tab, setTab] = useState<"accounts" | "readings">("accounts");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [local, setLocal] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [binding, setBinding] = useState<Account | null>(null);
  const [reviewing, setReviewing] = useState<Reading | null>(null);
  const [importing, setImporting] = useState(false);
  const [profileId, setProfileId] = useState<number | null>(null);
  const accounts = useApi<{ items: Account[]; total: number }>(allowed && tab === "accounts"
    ? `/subscribers?q=${encodeURIComponent(query)}&page=${page}` : null, revision + local);
  const readings = useApi<{ items: Reading[]; total: number }>(allowed && tab === "readings"
    ? `/subscribers/readings/list?page=${page}` : null, revision + local);
  const stats = useApi<RegistryStats>(allowed ? "/subscribers/stats" : null, revision + local);
  const result = tab === "accounts" ? accounts : readings;
  const current = editing && editing !== "new" ? editing : null;

  async function mutate(path: string, method: string, body: unknown) {
    setBusy(true); setError("");
    try {
      await api(path, { method, body: JSON.stringify(body) });
      setLocal((n) => n + 1); setEditing(null); setBinding(null); setReviewing(null);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  if (!allowed) return <Empty title="Қолжетімділік шектелген" text="Абоненттер реестрін бас әкімші басқарады." />;
  return <>
    <PageTitle eyebrow="АБОНЕНТТЕР" title="Абоненттер және көрсеткіштер"
      description="Дербес шоттарды тіркеу, Telegram қолжетімділігін растау және газ көрсеткіштерін тексеру."
      action={<div className="subscriber-toolbar">
        <Button variant="outline" onClick={() => void downloadSubscribersExport("csv")}>CSV экспорт</Button>
        <Button variant="outline" onClick={() => void downloadSubscribersExport("xlsx")}>Excel экспорт</Button>
        <Button variant="outline" onClick={() => setImporting(true)}><FileUp size={17} /> Файлдан қосу</Button>
        <Button onClick={() => { setError(""); setEditing("new"); }}><Plus size={17} /> Абонент қосу</Button>
      </div>} />
    {stats.data && <p className="section-note">
      {formatPeriod(stats.data.period)} айы бойынша: <strong>{stats.data.total}</strong> байланысқан абоненттен{" "}
      <strong>{stats.data.accepted}</strong> көрсеткіш қабылданды, <strong>{stats.data.pending}</strong> тексерілуде,{" "}
      <strong>{stats.data.missing}</strong> әлі көрсеткіш жібермеген.
    </p>}
    <div className="subscriber-toolbar">
      <Button variant={tab === "accounts" ? "default" : "outline"} onClick={() => { setTab("accounts"); setPage(1); }}>Абоненттер</Button>
      <Button variant={tab === "readings" ? "default" : "outline"} onClick={() => { setTab("readings"); setPage(1); }}>Газ көрсеткіштері</Button>
      {tab === "accounts" && <form className="subscriber-search" onSubmit={(e) => {
        e.preventDefault(); setQuery(String(new FormData(e.currentTarget).get("q") || "")); setPage(1);
      }}><input name="q" placeholder="Дербес шот, есептегіш немесе аты-жөні" aria-label="Абонентті іздеу" maxLength={100} />
        <Button type="submit" variant="outline"><Search size={16} /> Іздеу</Button></form>}
    </div>
    <ErrorBox message={editing || binding || reviewing ? "" : error || result.error} />
    <section className="panel">
      <div className="panel-heading"><h2>{tab === "accounts" ? "Тіркелген абоненттер" : "Жіберілген көрсеткіштер"}
        <span className="count-chip">{result.data?.total || 0}</span></h2></div>
      {result.loading ? <Loading /> : !result.data?.items.length ?
        <Empty title={tab === "accounts" ? "Абоненттер табылмады" : "Көрсеткіштер жоқ"}
          text={tab === "accounts" ? "Алдымен тексерілген деректермен абонентті тіркеңіз." : "Тұрғын жіберген көрсеткіштер осы жерде пайда болады."} /> :
        <div className="table-scroll"><table><thead><tr>{(tab === "accounts"
          ? ["ДЕРБЕС ШОТ / ЕСЕПТЕГІШ", "АБОНЕНТ", "ТЕЛЕФОН", "TELEGRAM", "ӘРЕКЕТ"]
          : ["ДЕРБЕС ШОТ", "КЕЗЕҢ", "КӨРСЕТКІШ", "ШЫҒЫН", "КҮЙІ", "ӘРЕКЕТ"]
        ).map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>
          {tab === "accounts" ? accounts.data?.items.map((a) => <tr key={a.id}>
            <td><strong>{a.account_number}</strong><br /><small>{a.meter_number}</small></td>
            <td><strong>{a.full_name}</strong><br /><small>{a.address}</small>{!a.active && <p>Бұғатталған</p>}</td>
            <td>{a.phone || "Тіркелмеген"}</td>
            <td>{a.telegram_user_id ? <><strong>Расталған</strong><br /><small>{a.telegram_user_id}</small></> : "Расталмаған"}</td>
            <td><Button size="sm" variant="ghost" onClick={() => setProfileId(a.id)}>Профиль</Button>
              <Button size="sm" variant="ghost" onClick={() => { setError(""); setEditing(a); }}>Өзгерту</Button>
              <Button size="sm" variant="ghost" onClick={() => { setError(""); setBinding(a); }}>Қолжетімділік</Button></td>
          </tr>) : readings.data?.items.map((r) => <tr key={r.id}>
            <td><strong>{r.account_number}</strong><br /><small>{r.full_name} · {r.meter_number}</small></td>
            <td>{formatPeriod(r.period)}</td><td>{r.value === null ? "Тексерілуде" : `${r.value} м³`}</td>
            <td>{r.consumption === null ? "—" : `${r.consumption} м³`}</td>
            <td>{readingLabels[r.status]}{r.review_note && <p className="section-note">{r.review_note}</p>}</td>
            <td>{r.status === "PENDING" && <Button size="sm" variant="outline"
              onClick={() => { setError(""); setReviewing(r); }}>Тексеру</Button>}</td>
          </tr>)}
        </tbody></table></div>}
      <div className="subscriber-toolbar"><Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Алдыңғы</Button>
        <span>{page}-бет</span><Button variant="outline" disabled={page * 25 >= (result.data?.total || 0)}
          onClick={() => setPage(page + 1)}>Келесі</Button></div>
    </section>
    <p className="section-note">Шот пен есептегіш нөмірі бірегей. Тұрғынның аты-жөні мен мекенжайы тек қолжетімділік расталған соң көрсетіледі.
      Алғашқы қабылданған көрсеткіш — бастапқы мән; шығын келесі қабылданған көрсеткіштен есептеледі.</p>

    <Dialog open={editing !== null} onOpenChange={(open) => { if (!open && !busy) setEditing(null); }}>
      <DialogContent title={current ? "Абонентті өзгерту" : "Жаңа абонент"}
        description="Тек тексерілген деректерді енгізіңіз. Телефонды не жеке деректерді өзгерту Telegram байланысын жояды.">
        <form key={current?.id || "new"} className="form-stack" onSubmit={(e) => {
          e.preventDefault(); const form = new FormData(e.currentTarget);
          const body = { account_number: String(form.get("account_number")), meter_number: String(form.get("meter_number")),
            full_name: String(form.get("full_name")), address: String(form.get("address")), phone: String(form.get("phone") || "") || null,
            ...(current ? { version: current.version, active: form.get("active") === "true" } : {}) };
          void mutate(current ? `/subscribers/${current.id}` : "/subscribers", current ? "PUT" : "POST", body);
        }}>
          <label>Дербес шот<input name="account_number" required pattern="[0-9]{6,20}" minLength={6} maxLength={20}
            readOnly={!!current} defaultValue={current?.account_number} inputMode="numeric" /></label>
          <label>Есептегіштің зауыттық нөмірі<input name="meter_number" required minLength={3} maxLength={40}
            pattern="[A-Za-z0-9\-]+" readOnly={!!current} defaultValue={current?.meter_number} /></label>
          <label>Аты-жөні<input name="full_name" required minLength={2} maxLength={200} defaultValue={current?.full_name} /></label>
          <label>Мекенжай<input name="address" required minLength={3} maxLength={500} defaultValue={current?.address} /></label>
          <label>Тексерілген телефон<input name="phone" type="tel" maxLength={32} placeholder="+7XXXXXXXXXX" defaultValue={current?.phone || ""} />
            <small>Телефон болмаса, қолжетімділікті әкімші қолмен растайды.</small></label>
          {current && <label>Күйі<select name="active" defaultValue={String(current.active)}>
            <option value="true">Белсенді</option><option value="false">Бұғатталған</option></select></label>}
          <ErrorBox message={error} /><Button type="submit" disabled={busy}>{busy ? "Сақталуда…" : "Сақтау"}</Button>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={binding !== null} onOpenChange={(open) => { if (!open && !busy) setBinding(null); }}>
      <DialogContent title="Telegram қолжетімділігі" description="Алдымен тұрғынның осы шотқа құқығын бөлек тексеріңіз. ID тұрғынға /start командасында көрсетіледі.">
        {binding && <form key={binding.id} className="form-stack" onSubmit={(e) => {
          e.preventDefault(); const form = new FormData(e.currentTarget); const id = String(form.get("telegram_user_id") || "").trim();
          void mutate(`/subscribers/${binding.id}/binding`, "POST", { telegram_user_id: id ? Number(id) : null,
            version: binding.version, reason: String(form.get("reason")) });
        }}>
          <p>{binding.account_number} · {binding.full_name}</p>
          <label>Telegram ID<input name="telegram_user_id" inputMode="numeric" pattern="[0-9]+" maxLength={16}
            defaultValue={binding.telegram_user_id || ""} /><small>Байланысты жою үшін бос қалдырыңыз.</small></label>
          <label>Растау немесе жою негізі<textarea name="reason" required minLength={10} maxLength={300} /></label>
          {binding.binding_note && <p className="section-note">Соңғы негіз: {binding.binding_note}</p>}
          <ErrorBox message={error} /><Button type="submit" disabled={busy}>Қолжетімділікті сақтау</Button>
        </form>}
      </DialogContent>
    </Dialog>
    <Dialog open={reviewing !== null} onOpenChange={(open) => { if (!open && !busy) setReviewing(null); }}>
      <DialogContent title="Көрсеткішті тексеру" description="Тұрғын тек фото жіберген. Есептегіштің көрсеткішін фотодан оқып, өзіңіз енгізіңіз.">
        {reviewing && <ReviewForm reviewing={reviewing} busy={busy} error={error}
          onSubmit={(body) => mutate(`/subscribers/readings/${reviewing.id}/review`, "POST", body)} />}
      </DialogContent>
    </Dialog>
    <ImportDialog open={importing} busy={busy} onClose={() => setImporting(false)}
      onImported={() => setLocal((n) => n + 1)} />
    <ProfileDialog accountId={profileId} onClose={() => setProfileId(null)} />
  </>;
}
