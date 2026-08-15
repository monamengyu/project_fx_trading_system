// Three-panel layout:
//   left   -> market data / rates
//   center -> trade blotter (main area)
//   right  -> new trade entry
export function Layout({ left, center, right }) {
  return (
    <main className="layout">
      <section className="panel panel--left">{left}</section>
      <section className="panel panel--center">{center}</section>
      <section className="panel panel--right">{right}</section>
    </main>
  );
}
