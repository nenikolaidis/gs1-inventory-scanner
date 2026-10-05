import { useEffect, type ComponentType } from "react";

import { useAuth } from "./auth";
import Account from "./pages/Account";
import Activity from "./pages/Activity";
import Counts from "./pages/Counts";
import History from "./pages/History";
import Locations from "./pages/Locations";
import More from "./pages/More";
import Login from "./pages/Login";
import Products from "./pages/Products";
import ScanPage from "./pages/Scan";
import Setup from "./pages/Setup";
import Stock from "./pages/Stock";
import Users from "./pages/Users";
import { Link, navigate, usePath } from "./router";

interface NavItem {
  path: string;
  label: string;
  icon: string;
  adminOnly?: boolean;
}

// Top navigation (desktop).
const NAV: NavItem[] = [
  { path: "/scan", label: "Scan", icon: "▦" },
  { path: "/stock", label: "Stock", icon: "▤" },
  { path: "/history", label: "History", icon: "☰" },
  { path: "/locations", label: "Locations", icon: "⌖" },
  { path: "/counts", label: "Counts", icon: "✓" },
  { path: "/products", label: "Products", icon: "▢" },
  { path: "/users", label: "Users", icon: "☺", adminOnly: true },
  { path: "/activity", label: "Activity", icon: "⏱", adminOnly: true },
  { path: "/account", label: "Account", icon: "⚙" },
];

// Bottom tab bar (phones): the rest is under "More".
const TABS: NavItem[] = [
  ...NAV.slice(0, 4),
  { path: "/more", label: "More", icon: "⋯" },
];
const UNDER_MORE = ["/more", "/counts", "/products", "/users", "/activity", "/account"];

const ADMIN_PAGES = NAV.filter((item) => item.adminOnly).map((item) => item.path);

const PAGES: Record<string, ComponentType> = {
  "/scan": ScanPage,
  "/stock": Stock,
  "/more": More,
  "/history": History,
  "/products": Products,
  "/locations": Locations,
  "/users": Users,
  "/counts": Counts,
  "/activity": Activity,
  "/account": Account,
};

export default function App() {
  const { user, needsSetup, loading } = useAuth();
  const fullPath = usePath();
  // Pages with an ID in the path (e.g. /counts/12) are handled by their list page.
  const path = /^\/counts\/\d+$/.test(fullPath) ? "/counts" : fullPath;

  useEffect(() => {
    if (user && !PAGES[path]) navigate("/scan", { replace: true });
  }, [user, path]);

  if (loading) return <div className="center-screen">Loading…</div>;
  if (needsSetup) return <Setup />;
  if (!user) return <Login />;

  const nav = NAV.filter((item) => !item.adminOnly || user.role === "admin");
  const Page = (ADMIN_PAGES.includes(path) && user.role !== "admin" ? null : PAGES[path]) ?? ScanPage;

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/scan" className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} />
          GS1 Scanner
        </Link>
        <nav className="topnav" aria-label="Main">
          {nav.map((item) => (
            <Link key={item.path} to={item.path} aria-current={path === item.path ? "page" : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>
        <span className="topbar-user">{user.display_name}</span>
      </header>
      <main className="content">
        <Page />
      </main>
      <nav className="tabbar" aria-label="Main">
        {TABS.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            aria-current={
              path === item.path || (item.path === "/more" && UNDER_MORE.includes(path)) ? "page" : undefined
            }
          >
            <span className="tab-icon" aria-hidden="true">
              {item.icon}
            </span>
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
