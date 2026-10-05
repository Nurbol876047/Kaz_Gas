"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bell,
  ChevronDown,
  CircleAlert,
  ClipboardList,
  FileChartColumn,
  Flame,
  LayoutDashboard,
  LogOut,
  Menu,
  Search,
  Settings2,
  UsersRound,
  X,
} from "lucide-react";
import { useAuth } from "./auth-provider";
import { useApi } from "@/hooks/use-api";
import type { Settings as Config } from "@/types";
import { ROLE_LABELS } from "@/types";
import { Applications } from "./applications";
import { Dashboard } from "./dashboard";
import { ApplicationDetail } from "./application-detail";
import { Reports } from "./reports";
import { Staff } from "./staff";
import { Subscribers } from "./subscribers";
import { Settings } from "./settings";
import { Empty, Loading } from "./common";
const links = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/applications", label: "Өтінімдер", icon: ClipboardList },
  { href: "/emergencies", label: "Авариялық өтінімдер", icon: CircleAlert },
  { href: "/staff", label: "Қызметкерлер", icon: UsersRound },
  { href: "/subscribers", label: "Абоненттер", icon: UsersRound },
  { href: "/reports", label: "Есептер", icon: FileChartColumn },
  { href: "/settings", label: "Баптаулар", icon: Settings2 },
];
type Notice = {
  id: number;
  number: string;
  priority: string;
  kind: string;
  key: string;
};
export function Workspace() {
  const { admin, loading, logout } = useAuth(),
    path = usePathname(),
    router = useRouter(),
    search = useSearchParams().toString();
  const [revision, setRevision] = useState(0),
    [online, setOnline] = useState(false),
    [mobile, setMobile] = useState(false),
    [notices, setNotices] = useState<Notice[]>([]),
    [showNotices, setShowNotices] = useState(false),
    [toast, setToast] = useState<Notice | null>(null),
    [logoutError, setLogoutError] = useState("");
  const config = useApi<Config>(admin ? "/settings" : null, revision);
  useEffect(() => {
    if (!admin) return;
    const source = new EventSource("/api/events");
    const refresh = () => setRevision((n) => n + 1);
    let batch: ReturnType<typeof setTimeout> | undefined;
    const scheduleRefresh = () => {
      if (batch) return;
      batch = setTimeout(() => { batch = undefined; refresh(); }, 200);
    };
    source.addEventListener("ready", () => {
      setOnline(true);
      refresh();
    });
    source.addEventListener("application", (e) => {
      try {
        const item = {
          ...JSON.parse((e as MessageEvent).data),
          key: (e as MessageEvent).lastEventId,
        };
        scheduleRefresh();
        if (item.kind === "created") {
          setNotices((n) => [item, ...n].slice(0, 20));
          setToast(item);
        }
      } catch {}
    });
    source.addEventListener("expired", () => {
      source.close();
      window.dispatchEvent(new Event("session-expired"));
    });
    source.onerror = () => setOnline(false);
    const poll = setInterval(refresh, 30000);
    return () => {
      source.close();
      clearInterval(poll);
      clearTimeout(batch);
    };
  }, [admin]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => setMobile(false), [path]);
  if (loading || !admin)
    return (
      <main className="auth-loading">
        <Loading />
      </main>
    );
  const active = links.find((l) =>
    l.href === "/" ? path === "/" : path.startsWith(l.href),
  );
  const detail = path.match(/^\/applications\/(\d+)$/);
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Мазмұнға өту
      </a>
      {mobile && (
        <button
          className="sidebar-scrim"
          aria-label="Мәзірді жабу"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={`sidebar ${mobile ? "is-open" : ""}`}>
        <Link href="/" className="brand">
          <span className="brand-icon">
            <Flame size={23} />
          </span>
          <span>
            QALA<span className="brand-gas">GAS</span>
          </span>
        </Link>
        <div className="workspace-label">
          <span className="workspace-dot" /> Қызмет көрсету орталығы
        </div>
        <span className="nav-heading">НЕГІЗГІ МӘЗІР</span>
        <nav>
          {links.filter((link) => link.href !== "/subscribers" || admin.role === "SUPER_ADMIN").map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={
                (href === "/" ? path === "/" : path.startsWith(href))
                  ? "active"
                  : ""
              }
            >
              <Icon size={19} strokeWidth={1.7} />
              <span>{label}</span>
              {href === "/emergencies" && <span className="nav-alert-dot" />}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="support-card">
            <span className="support-icon">
              <Flame size={22} />
            </span>
            <strong>
              {config.data?.organization_name || "Қызмет көрсету"}
            </strong>
            <p>
              Тұрғындарға жақын.
              <br />
              Әр өтінімге жауапты.
            </p>
            {config.data?.contact_phone && (
              <a href={`tel:${config.data.contact_phone}`}>
                {config.data.contact_phone}
              </a>
            )}
          </div>
          <span className="sidebar-version">
            UTILITY DESK <span>v1.0</span>
          </span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu icon-button"
              aria-label="Мәзірді ашу"
              onClick={() => setMobile(true)}
            >
              <Menu size={21} />
            </button>
            <span className="breadcrumb">
              Жұмыс кеңістігі <span>/</span>{" "}
              <strong>{active?.label || "Өтінім"}</strong>
            </span>
          </div>
          <div className="topbar-actions">
            <form
              className="header-search"
              onSubmit={(e) => {
                e.preventDefault();
                const q = String(new FormData(e.currentTarget).get("q") || "");
                router.push(`/applications?q=${encodeURIComponent(q)}`);
              }}
            >
              <Search size={17} />
              <input
                name="q"
                aria-label="Жалпы іздеу"
                placeholder="Іздеу…"
                maxLength={100}
              />
              <kbd>↵</kbd>
            </form>
            <span className={`live-label ${online ? "online" : ""}`}>
              <i />
              {online ? "Тікелей" : "Қайта қосылу…"}
            </span>
            <div className="notification-wrap">
              <button
                className="icon-button notification-button"
                aria-label="Хабарландырулар"
                aria-expanded={showNotices}
                onClick={() => setShowNotices(!showNotices)}
              >
                <Bell size={20} />
                {notices.length > 0 && <i />}
              </button>
              {showNotices && (
                <div className="notification-popover">
                  <h3>
                    Хабарландырулар{" "}
                    <button
                      aria-label="Жабу"
                      onClick={() => setShowNotices(false)}
                    >
                      <X size={16} />
                    </button>
                  </h3>
                  {notices.length ? (
                    notices.map((n) => (
                      <Link
                        key={n.key}
                        href={`/applications/${n.id}`}
                        onClick={() => setShowNotices(false)}
                      >
                        <span>
                          {n.priority === "CRITICAL"
                            ? "🚨 Жаңа авариялық өтінім"
                            : "Жаңа өтінім"}
                        </span>
                        <strong>{n.number}</strong>
                      </Link>
                    ))
                  ) : (
                    <p>Жаңа хабарландырулар жоқ</p>
                  )}
                </div>
              )}
            </div>
            <span className="header-divider" />
            <details className="profile-menu">
              <summary>
                <span className="avatar">
                  {admin.name.slice(0, 2).toUpperCase()}
                </span>
                <span className="profile-name">
                  <strong>{admin.name}</strong>
                  <small>{ROLE_LABELS[admin.role]}</small>
                </span>
                <ChevronDown size={14} />
              </summary>
              <div>
                <p>{admin.email}</p>
                <button
                  onClick={() =>
                    logout().catch((e) => setLogoutError(e.message))
                  }
                >
                  <LogOut size={16} />
                  Шығу
                </button>
                {logoutError && <p role="alert">{logoutError}</p>}
              </div>
            </details>
          </div>
        </header>
        <main id="main" className="main-content">
          {detail ? (
            <ApplicationDetail key={path} id={detail[1]} revision={revision} />
          ) : path === "/" ? (
            <Dashboard revision={revision} />
          ) : path === "/applications" ? (
            <Applications key={path + search} revision={revision} />
          ) : path === "/emergencies" ? (
            <Applications key={path} revision={revision} emergency />
          ) : path === "/reports" ? (
            <Reports revision={revision} />
          ) : path === "/staff" ? (
            <Staff revision={revision} />
          ) : path === "/subscribers" ? (
            <Subscribers revision={revision} />
          ) : path === "/settings" ? (
            <Settings revision={revision} />
          ) : (
            <Empty
              title="Бет табылмады"
              text="Мәзірден қажетті бөлімді таңдаңыз."
            />
          )}
          <footer className="main-footer">
            <span>
              © {new Date().getFullYear()}{" "}
              {config.data?.organization_name || "Qala Gas"}
            </span>
            <span>Қалалық қызметтер · Өтінімдерді басқару</span>
          </footer>
        </main>
      </div>
      {toast && (
        <div
          className={`toast ${toast.priority === "CRITICAL" ? "toast-urgent" : ""}`}
          role="status"
        >
          <Link href={`/applications/${toast.id}`}>
            <strong>
              {toast.priority === "CRITICAL"
                ? "🚨 Жаңа авариялық өтінім"
                : "Жаңа өтінім"}
            </strong>
            <span>{toast.number}</span>
          </Link>
          <button aria-label="Хабарламаны жабу" onClick={() => setToast(null)}>
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}
