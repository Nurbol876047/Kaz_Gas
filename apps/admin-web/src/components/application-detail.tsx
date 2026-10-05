"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  Clock3,
  ImageIcon,
  MapPin,
  MessageSquare,
  Send,
  UserRound,
} from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { api } from "@/services/api";
import { dateOnly, dateTime } from "@/lib/utils";
import { useAuth } from "./auth-provider";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogTrigger } from "./ui/dialog";
import { ErrorBox, Loading, PriorityBadge, StatusBadge } from "./common";
import type { Admin, Application, History, Status } from "@/types";
import { PRIORITY_LABELS, STATUS_LABELS, TYPE_LABELS } from "@/types";
const Map = dynamic(() => import("./map"), {
  ssr: false,
  loading: () => <Loading />,
});
const transitions: Record<Status, Status[]> = {
  NEW: ["IN_PROGRESS", "REJECTED"],
  IN_PROGRESS: ["COMPLETED", "REJECTED"],
  COMPLETED: [],
  REJECTED: [],
};
export function ApplicationDetail({
  id,
  revision,
}: {
  id: string;
  revision: number;
}) {
  const { admin } = useAuth();
  const [local, setLocal] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState("");
  const result = useApi<Application>(`/applications/${id}`, revision + local),
    history = useApi<History[]>(
      `/applications/${id}/history`,
      revision + local,
    ),
    admins = useApi<Admin[]>("/admins", revision);
  async function mutate(
    path: string,
    data: Record<string, unknown>,
    method = "PATCH",
  ) {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      await api(`/applications/${id}${path}`, {
        method,
        body: JSON.stringify({ ...data, version: result.data!.version }),
      });
      setLocal((n) => n + 1);
      setSaved("Өзгерістер сақталды");
    } catch (e) {
      setError((e as Error).message);
      setLocal((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }
  if (!result.data)
    return result.error ? <ErrorBox message={result.error} /> : <Loading />;
  const a = result.data,
    manager = admin?.role !== "OPERATOR";
  return (
    <>
      <Link href="/applications" className="back-link">
        <ArrowLeft size={16} /> Өтінімдерге оралу
      </Link>
      <div className="detail-title">
        <div>
          <span className="eyebrow">ӨТІНІМ КАРТОЧКАСЫ</span>
          <h1>{a.application_number}</h1>
          <p>
            <Clock3 size={14} /> {dateTime(a.created_at)}
          </p>
        </div>
        <div className="detail-badges">
          <StatusBadge status={a.status} />
          <PriorityBadge priority={a.priority} />
        </div>
      </div>
      {a.priority === "CRITICAL" && (
        <div className="emergency-note">
          <strong>🚨 АВАРИЯ</strong> Есептеу құралынан газ шығуы. Шұғыл өңдеуді
          қажет етеді.
        </div>
      )}
      <ErrorBox message={error || result.error} />
      {saved && (
        <div className="success" role="status">
          <Check size={16} />
          {saved}
        </div>
      )}
      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel">
            <div className="panel-heading">
              <h2>Өтінім туралы</h2>
              <UserRound size={18} />
            </div>
            <dl className="details">
              <div>
                <dt>Дербес шот</dt>
                <dd className="mono">{a.personal_account}</dd>
                <small>
                  {a.subscriber_verified
                    ? "Өтінім жіберілген кезде абонент реестрімен расталған"
                    : "Шот иесі абонент реестрімен расталмаған"}
                </small>
              </div>
              <div>
                <dt>Өтінім түрі</dt>
                <dd>{TYPE_LABELS[a.application_type]}</dd>
              </div>
              <div>
                <dt>Тұрғын</dt>
                <dd>
                  {a.user.first_name} {a.user.last_name}
                </dd>
              </div>
              <div>
                <dt>Telegram</dt>
                <dd>
                  {a.user.telegram_username ? (
                    <a
                      href={`https://t.me/${a.user.telegram_username}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      @{a.user.telegram_username} ↗
                    </a>
                  ) : (
                    a.user.telegram_user_id
                  )}
                </dd>
              </div>
              {a.requested_date && (
                <div>
                  <dt>МПИ күні</dt>
                  <dd>
                    <CalendarDays size={16} /> {dateOnly(a.requested_date)}
                  </dd>
                </div>
              )}
              <div>
                <dt>Орындаушы</dt>
                <dd>{a.assignee_name || "Тағайындалмаған"}</dd>
              </div>
            </dl>
          </section>
          {!!a.files?.length && (
            <section className="panel">
              <div className="panel-heading">
                <h2>
                  Фотосуреттер{" "}
                  <span className="count-chip">{a.files.length}</span>
                </h2>
                <ImageIcon size={18} />
              </div>
              <div className="photos">
                {a.files.map((file) => (
                  <Dialog key={file.id}>
                    <div>
                      <DialogTrigger asChild>
                        <button className="photo-button">
                          <img
                            src={file.url}
                            alt={
                              file.file_type === "METER_PHOTO"
                                ? "Есептеу құралы"
                                : "Газ шығып жатқан жер"
                            }
                          />
                          <span>
                            <ArrowUpRight size={16} /> Үлкейту
                          </span>
                        </button>
                      </DialogTrigger>
                      <p>
                        {file.file_type === "METER_PHOTO"
                          ? "Есептеу құралы"
                          : "Газ шығып жатқан жер"}
                      </p>
                    </div>
                    <DialogContent title="Өтінім фотосы" wide>
                      <img
                        className="lightbox-image"
                        src={file.url}
                        alt="Өтінім фотосы толық өлшемде"
                      />
                    </DialogContent>
                  </Dialog>
                ))}
              </div>
            </section>
          )}
          {a.latitude !== null && a.longitude !== null && (
            <section className="panel">
              <div className="panel-heading">
                <h2>
                  <MapPin size={18} /> Геолокация
                </h2>
                <a
                  className="text-link"
                  href={`https://www.openstreetmap.org/?mlat=${a.latitude}&mlon=${a.longitude}#map=17/${a.latitude}/${a.longitude}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Картадан ашу <ArrowUpRight size={15} />
                </a>
              </div>
              <Map latitude={a.latitude} longitude={a.longitude} />
              <div className="coordinates">
                <span>
                  Latitude <strong>{a.latitude}</strong>
                </span>
                <span>
                  Longitude <strong>{a.longitude}</strong>
                </span>
              </div>
            </section>
          )}
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <Clock3 size={18} /> Өзгерістер тарихы
              </h2>
            </div>
            <ErrorBox message={history.error} />
            <div className="timeline">
              {history.data?.map((h) => (
                <div className="timeline-item" key={h.id}>
                  <i />
                  <div>
                    <strong>
                      {h.old_status && h.old_status !== h.new_status
                        ? `${STATUS_LABELS[h.old_status]} → `
                        : ""}
                      {STATUS_LABELS[h.new_status]}
                    </strong>
                    <p>{h.comment || "Мәртебе өзгертілді"}</p>
                    <small>
                      {h.admin_name || "Telegram"} · {dateTime(h.created_at)}
                      {h.public_comment
                        ? " · Тұрғынға жіберілді"
                        : " · Ішкі жазба"}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
        <aside className="detail-aside">
          <section className="panel">
            <div className="panel-heading">
              <h2>Өтінімді өңдеу</h2>
            </div>
            <div className="form-stack">
              {transitions[a.status].length ? (
                <form
                  key={`status-${a.version}`}
                  onSubmit={(e) => {
                    e.preventDefault();
                    const f = new FormData(e.currentTarget);
                    mutate("/status", {
                      status: f.get("status"),
                      comment: f.get("comment") || null,
                      public_comment: f.get("public") === "on",
                    });
                  }}
                >
                  <label>
                    Жаңа мәртебе
                    <select name="status">
                      {transitions[a.status].map((s) => (
                        <option value={s} key={s}>
                          {STATUS_LABELS[s]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Түсініктеме
                    <textarea
                      name="comment"
                      rows={3}
                      maxLength={2000}
                      placeholder="Қажет болса, түсініктеме қосыңыз…"
                    />
                  </label>
                  <label className="checkbox">
                    <input name="public" type="checkbox" />
                    Түсініктемені тұрғынға жіберу
                  </label>
                  <Button disabled={busy} type="submit">
                    <Check size={16} /> Мәртебені өзгерту
                  </Button>
                </form>
              ) : (
                <p className="closed-note">
                  <Check size={18} /> Өтінім жабылған
                </p>
              )}
              {manager && (
                <>
                  <hr />
                  <form
                    key={`assign-${a.version}`}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const f = new FormData(e.currentTarget);
                      mutate("/assign", {
                        assigned_to: f.get("assigned")
                          ? Number(f.get("assigned"))
                          : null,
                      });
                    }}
                  >
                    <label>
                      Орындаушы
                      <select
                        name="assigned"
                        defaultValue={a.assigned_to || ""}
                      >
                        <option value="">Тағайындалмаған</option>
                        {admins.data
                          ?.filter((x) => x.active)
                          .map((x) => (
                            <option value={x.id} key={x.id}>
                              {x.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <Button variant="outline" disabled={busy} type="submit">
                      Орындаушыны тағайындау
                    </Button>
                  </form>
                  <hr />
                  <form
                    key={`priority-${a.version}`}
                    onSubmit={(e) => {
                      e.preventDefault();
                      mutate("", {
                        priority: new FormData(e.currentTarget).get("priority"),
                      });
                    }}
                  >
                    <label>
                      Басымдық
                      <select
                        name="priority"
                        defaultValue={a.priority}
                        disabled={a.application_type === "GAS_LEAK"}
                      >
                        {Object.entries(PRIORITY_LABELS).map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {a.application_type !== "GAS_LEAK" && (
                      <Button variant="outline" disabled={busy} type="submit">
                        Басымдықты сақтау
                      </Button>
                    )}
                  </form>
                </>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <MessageSquare size={17} /> Түсініктеме
              </h2>
            </div>
            <form
              key={`comment-${a.version}`}
              className="form-stack"
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                mutate(
                  "/comments",
                  {
                    comment: f.get("comment"),
                    public_comment: f.get("public") === "on",
                  },
                  "POST",
                );
              }}
            >
              <label className="sr-only" htmlFor="note">
                Түсініктеме
              </label>
              <textarea
                id="note"
                name="comment"
                required
                maxLength={2000}
                rows={5}
                placeholder="Орындалған жұмыс немесе қосымша ақпарат…"
              />
              <label className="checkbox">
                <input name="public" type="checkbox" />
                Тұрғынға Telegram арқылы жіберу
              </label>
              <Button disabled={busy} variant="outline" type="submit">
                <Send size={15} /> Қосу
              </Button>
              <small className="muted">
                Белгі қойылмаса, түсініктемені тек қызметкерлер көреді.
              </small>
            </form>
          </section>
        </aside>
      </div>
    </>
  );
}
