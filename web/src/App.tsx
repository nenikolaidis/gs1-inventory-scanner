import { useEffect, type ComponentType } from "react";

import { useAuth } from "./auth";
import Account from "./pages/Account";
import History from "./pages/History";
import Locations from "./pages/Locations";
import Login from "./pages/Login";
import Products from "./pages/Products";
import ScanPage from "./pages/Scan";
import Setup from "./pages/Setup";
import Users from "./pages/Users";
import { Link, navigate, usePath } from "./router";

interface NavItem {
  path: string;
  label: string;
  icon: string;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { path: "/scan", label: "Scan", icon: "▦" },
  { path: "/history", label: "History", icon: "☰" },
  { path: "/products", label: "Products", icon: "▢" },
  { path: "/locations", label: "Locations", icon: "⌖" },
  { path: "/users", label: "Users", icon: "☺", adminOnly: true },
  { path: "/account", label: "Account", icon: "⚙" },
];

const PAGES: Record<string, ComponentType> = {
  "/scan": ScanPage,
  "/history": History,
  "/products": Products,
  "/locations": Locations,
  "/users": Users,
  "/account": Account,
};

export default function App() {
  const { user, needsSetup, loading } = useAuth();
  const path = usePath();

  useEffect(() => {
    if (user && !PAGES[path]) navigate("/scan", { replace: true });
  }, [user, path]);

  if (loading) return <div className="center-screen">Loading…</div>;
  if (needsSetup) return <Setup />;
  if (!user) return <Login />;

  const nav = NAV.filter((item) => !item.adminOnly || user.role === "admin");
  const Page = (path === "/users" && user.role !== "admin" ? null : PAGES[path]) ?? ScanPage;

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
        {nav.map((item) => (
          <Link key={item.path} to={item.path} aria-current={path === item.path ? "page" : undefined}>
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
