// Phone navigation for the pages that don't fit in the bottom tab bar.

import { useUser } from "../auth";
import { Link } from "../router";
import { PageHeader } from "../ui";

export default function More() {
  const user = useUser();
  const items = [
    { to: "/counts", label: "Stock counts", hint: "Review and apply counts" },
    { to: "/products", label: "Products", hint: "GTIN to SKU list" },
    ...(user.role === "admin"
      ? [
          { to: "/users", label: "Users", hint: "Accounts and roles" },
          { to: "/activity", label: "Activity", hint: "Who changed what, and logins" },
        ]
      : []),
    { to: "/account", label: "Account", hint: `${user.display_name} · password · log out` },
  ];
  return (
    <>
      <PageHeader title="More" />
      <ul className="menu-list">
        {items.map((item) => (
          <li key={item.to}>
            <Link to={item.to}>
              <strong>{item.label}</strong>
              <span className="muted small">{item.hint}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
