import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Methods", end: true },
  { to: "/compare", label: "Compare" },
  { to: "/trends", label: "Trends" },
  { to: "/trajectory", label: "Trajectory" },
  { to: "/submission", label: "Submission" },
];

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <h1>cbtrack</h1>
        <div className="sub">CAR-bench experiments</div>
        <nav className="nav">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {l.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
