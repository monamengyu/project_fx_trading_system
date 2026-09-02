// Trading dashboard layout:
//   main (left) : market data | positions on top, trade blotter filling the rest
//   side (right): new-trade form above natural-language trade entry, full-height rail
export function Layout({ topLeft, topCenter, main, sideTop, sideBottom }) {
  return (
    <main className="layout">
      <div className="layout__main">
        <section className="layout__top">
          <div className="panel">{topLeft}</div>
          <div className="panel">{topCenter}</div>
        </section>
        <section className="layout__blotter">
          <div className="panel">{main}</div>
        </section>
      </div>
      <aside className="layout__rail">
        <div className="panel">{sideTop}</div>
        <div className="panel">{sideBottom}</div>
      </aside>
    </main>
  );
}
