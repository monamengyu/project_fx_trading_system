// Trading dashboard layout:
//   top    : market data | positions | new trade
//   bottom : trade blotter (main, left) | natural-language trade entry (right)
export function Layout({ topLeft, topCenter, topRight, bottomLeft, bottomRight }) {
  return (
    <main className="layout">
      <section className="layout__top">
        <div className="panel">{topLeft}</div>
        <div className="panel">{topCenter}</div>
        <div className="panel">{topRight}</div>
      </section>
      <section className="layout__bottom">
        <div className="panel layout__bottom-main">{bottomLeft}</div>
        {bottomRight && <div className="panel layout__bottom-side">{bottomRight}</div>}
      </section>
    </main>
  );
}
