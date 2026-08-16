// Mirrors base.html's top nav (admin_portal/templates/base.html) so this
// SPA — mounted at /app, otherwise its own island with only a "back" link —
// gives access to the rest of the site instead of stranding the visitor.
// Every link here is a real page outside the SPA's router except Live
// Monitoring itself, so plain <a> tags (full navigation) throughout.
export default function AppNav() {
  return (
    <nav className="app-nav">
      <a href="/">Home</a>
      <a href="/insights">Insights</a>
      <a href="/cameras">Cameras</a>
      <a href="/app/cameras" className="active">Live Monitoring</a>
      <a href="/reviews">Review Queue</a>
      <a href="/jobs">Jobs</a>
      <a href="/floor">On the Floor</a>
    </nav>
  );
}
