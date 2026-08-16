// Trading dashboard layout:
//   leftTop    -> market data
//   leftBottom -> position summary
//   center     -> trade blotter (main area)
//   right      -> new trade entry
export function Layout({ leftTop, leftBottom, center, right }) {
  return (
    <main className="layout">
      <section className="layout__rail">
        <div className="panel">{leftTop}</div>
        <div className="panel">{leftBottom}</div>
      </section>
      <section className="panel">{center}</section>
      <section className="panel">{right}</section>
    </main>
  );
}
